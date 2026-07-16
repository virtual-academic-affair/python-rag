from __future__ import annotations

import asyncio

from app.integrations.storage.client import r2_storage
from app.modules.files.services.file_service import get_file_service
from app.modules.files.toc_tree.models.toc_tree import serialize_toc_structure
from app.modules.files.toc_tree.repositories.toc_tree_repository import FileTocTreeRepository


async def _fetch_file_and_toc_maps(file_ids: list[str]):
    file_svc = get_file_service()
    toc_repo = FileTocTreeRepository()

    files = await file_svc.get_files_by_ids(file_ids)
    file_map = {str(f.id): f for f in files}
    toc_docs = await toc_repo.find_by_file_ids(list(file_map.keys()))
    toc_map = {t.file_id: t for t in toc_docs}
    return file_map, toc_map


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
        storage_path = file_doc.storage_path or ""
        markdown_storage_path = (toc.markdown_storage_path if toc else "") or ""
        if not storage_path or not markdown_storage_path:
            continue
        result.append({
            "file_id": fid,
            "file_name": file_doc.display_name or "",
            "doc_description": (toc.doc_description if toc else "") or "",
            "lecturer_only": bool(getattr(file_doc, "lecturer_only", False)),
        })
    return result


async def hydrate_source_files(file_ids: list[str]) -> dict[str, dict]:
    """Hydrate accessed file IDs into source metadata for citation rendering."""
    if not file_ids:
        return {}

    file_map, toc_map = await _fetch_file_and_toc_maps(file_ids)

    async def build_source(fid: str) -> tuple[str, dict] | None:
        file_doc = file_map.get(fid)
        if not file_doc:
            return None
        toc = toc_map.get(fid)
        storage_path = file_doc.storage_path or ""
        markdown_storage_path = (toc.markdown_storage_path if toc else "") or ""
        original_url, markdown_url = await _resolve_source_urls(storage_path, markdown_storage_path)
        return fid, {
            "file_id": fid,
            "file_name": file_doc.display_name or "",
            "original_url": original_url,
            "markdown_url": markdown_url,
            "structure": serialize_toc_structure(toc.structure) if toc else [],
            "table_of_contents": file_doc.table_of_contents or [],
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
