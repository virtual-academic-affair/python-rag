from __future__ import annotations

import asyncio

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.core.config import settings
from app.integrations.redis.client import get_redis_client
from app.integrations.storage.client import r2_storage
from app.modules.files.services.file_service import get_file_service
from app.modules.files.toc_tree.models.toc_tree import serialize_toc_structure
from app.modules.files.toc_tree.repositories.toc_tree_repository import FileTocTreeRepository
from app.modules.rag.cache import file_entity_key


class FileEntityCacheEntry(BaseModel):
    """File and TOC fields shared by retrieval, inspection, and source building."""

    model_config = ConfigDict(extra="forbid")

    file_id: str
    file_name: str = ""
    original_filename: str = ""
    storage_path: str = ""
    markdown_storage_path: str = ""
    doc_name: str = ""
    doc_description: str = ""
    line_count: int = 0
    structure: list[dict] = Field(default_factory=list)
    table_of_contents: list[str] = Field(default_factory=list)
    custom_metadata: dict | None = None
    lecturer_only: bool = False


async def get_file_entities(file_ids: list[str]) -> dict[str, FileEntityCacheEntry]:
    """Hydrate exact file IDs through Redis, querying Mongo only for misses."""
    unique_ids = list(dict.fromkeys(file_id for file_id in file_ids if file_id))
    if not unique_ids:
        return {}

    redis = get_redis_client()
    await redis.connect()
    keys = [file_entity_key(file_id) for file_id in unique_ids]
    cached_values = await redis.mget_json(keys)
    entities: dict[str, FileEntityCacheEntry] = {}
    missing_ids: list[str] = []
    for file_id, payload in zip(unique_ids, cached_values):
        if payload is None:
            missing_ids.append(file_id)
            continue
        try:
            entry = FileEntityCacheEntry.model_validate(payload)
        except ValidationError:
            missing_ids.append(file_id)
            continue
        if entry.file_id != file_id:
            missing_ids.append(file_id)
            continue
        entities[file_id] = entry

    if not missing_ids:
        return entities

    file_svc = get_file_service()
    toc_repo = FileTocTreeRepository()
    files, toc_docs = await asyncio.gather(
        file_svc.get_files_by_ids(missing_ids),
        toc_repo.find_by_file_ids(missing_ids),
    )
    file_map = {str(f.id): f for f in files}
    toc_map = {t.file_id: t for t in toc_docs}
    writes = []
    for file_id in missing_ids:
        file_doc = file_map.get(file_id)
        if not file_doc:
            continue
        toc = toc_map.get(file_id)
        entry = FileEntityCacheEntry(
            file_id=file_id,
            file_name=file_doc.display_name or "",
            original_filename=file_doc.original_filename or "",
            storage_path=file_doc.storage_path or "",
            markdown_storage_path=(toc.markdown_storage_path if toc else "") or "",
            doc_name=(toc.doc_name if toc else "") or "",
            doc_description=(toc.doc_description if toc else "") or "",
            line_count=(toc.line_count if toc else 0) or 0,
            structure=serialize_toc_structure(toc.structure) if toc else [],
            table_of_contents=file_doc.table_of_contents or [],
            custom_metadata=(
                file_doc.custom_metadata.model_dump(mode="json")
                if file_doc.custom_metadata
                else None
            ),
            lecturer_only=bool(file_doc.lecturer_only),
        )
        entities[file_id] = entry
        writes.append(redis.set_json(
            file_entity_key(file_id),
            entry,
            ex=settings.RAG_ENTITY_CACHE_TTL_SECONDS,
        ))
    if writes:
        await asyncio.gather(*writes)
    return entities


async def _fetch_file_and_toc_maps(file_ids: list[str]):
    """Compatibility seam backed by the shared entity cache."""
    entities = await get_file_entities(file_ids)
    return entities, entities


async def hydrate_pageindex_candidate_files(candidate_ids: list[str]) -> list[dict]:
    """Hydrate traversal file IDs into the minimal payload used by rerank/agent."""
    if not candidate_ids:
        return []

    file_map, toc_map = await _fetch_file_and_toc_maps(candidate_ids)

    result: list[dict] = []
    for fid in candidate_ids:
        file_doc = file_map.get(fid)
        if not file_doc:
            continue
        toc = toc_map.get(fid)
        if isinstance(file_doc, FileEntityCacheEntry):
            storage_path = file_doc.storage_path
            markdown_storage_path = file_doc.markdown_storage_path
            file_name = file_doc.file_name
            doc_description = file_doc.doc_description
            lecturer_only = file_doc.lecturer_only
        else:
            storage_path = file_doc.storage_path or ""
            markdown_storage_path = (toc.markdown_storage_path if toc else "") or ""
            file_name = file_doc.display_name or ""
            doc_description = (toc.doc_description if toc else "") or ""
            lecturer_only = bool(getattr(file_doc, "lecturer_only", False))
        if not storage_path or not markdown_storage_path:
            continue
        result.append({
            "file_id": fid,
            "file_name": file_name,
            "doc_description": doc_description,
            "lecturer_only": lecturer_only,
        })
    return result


async def hydrate_source_files(file_ids: list[str]) -> dict[str, dict]:
    """Hydrate accessed file IDs into source metadata for citation rendering."""
    if not file_ids:
        return {}

    entity_map = await get_file_entities(file_ids)

    async def build_source(fid: str) -> tuple[str, dict] | None:
        entity = entity_map.get(fid)
        if not entity:
            return None
        original_url, markdown_url = await _resolve_source_urls(
            entity.storage_path,
            entity.markdown_storage_path,
        )
        return fid, {
            "file_id": fid,
            "file_name": entity.file_name,
            "original_url": original_url,
            "markdown_url": markdown_url,
            "structure": entity.structure,
            "table_of_contents": entity.table_of_contents,
        }

    results = await asyncio.gather(*(build_source(fid) for fid in file_ids))
    sources: dict[str, dict] = {}
    for item in results:
        if item:
            fid, source = item
            sources[fid] = source
    return sources


async def _resolve_source_urls(storage_path: str, markdown_storage_path: str) -> tuple[str, str]:
    async def get_orig():
        if storage_path:
            return await r2_storage.get_file_url(storage_path)
        return ""

    async def get_md():
        if markdown_storage_path:
            return await r2_storage.get_file_url(markdown_storage_path)
        return ""

    return await asyncio.gather(get_orig(), get_md())
