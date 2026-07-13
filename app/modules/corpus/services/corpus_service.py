from __future__ import annotations
import asyncio
import logging
from typing import Optional

from app.modules.corpus.repositories.corpus_node_repository import CorpusNodeRepository
from app.modules.corpus.models.corpus_node import CorpusNodeDocument
from app.modules.corpus.repositories.corpus_node_repository import would_create_cycle
from app.modules.corpus.dtos.create_topic import TopicCreateRequest
from app.modules.corpus.dtos.delete_topic import TopicDeleteResponse
from app.modules.corpus.dtos.list_topics import CorpusTopicListResponse
from app.modules.corpus.dtos.merge_topic import TopicMergeResponse
from app.modules.corpus.dtos.payload_topics import CorpusPayloadTopicsResponse
from app.modules.corpus.dtos.topic_out import (
    CorpusFileRefResponse,
    CorpusFaqRefResponse,
    CorpusStatsResponse,
    CorpusTopicDetailResponse,
    CorpusTopicSummaryResponse,
    CorpusTreeNodeResponse,
    CorpusTreeResponse,
)
from app.modules.metadata.dtos import FaqMetadataResponse, FileMetadataResponse
from app.modules.corpus.dtos.update_topic import TopicUpdateRequest
from app.modules.corpus.utils.node_keys import slugify_topic

logger = logging.getLogger(__name__)


def diff_links(old_keys: list[str], new_keys: list[str]) -> tuple[list[str], list[str]]:
    old, new = set(old_keys), set(new_keys)
    return ([k for k in new_keys if k not in old], [k for k in old_keys if k not in new])


class CorpusService:
    def __init__(self):
        self._repo: Optional[CorpusNodeRepository] = None

    def clear_cache(self) -> None:
        return None

    @property
    def repo(self) -> CorpusNodeRepository:
        if self._repo is None:
            self._repo = CorpusNodeRepository()
        return self._repo

    async def get_all_nodes(self) -> list[CorpusNodeDocument]:
        return await self.repo.get_all()

    @staticmethod
    def _filtered_ids(
        node: CorpusNodeDocument,
        allowed_file_ids: set[str] | None = None,
        allowed_faq_ids: set[str] | None = None,
    ) -> tuple[list[str], list[str], list[str], list[str]]:
        direct_file_ids = [item for item in node.direct_file_ids if allowed_file_ids is None or item in allowed_file_ids]
        direct_faq_ids = [item for item in node.direct_faq_ids if allowed_faq_ids is None or item in allowed_faq_ids]
        subtree_file_ids = [item for item in node.subtree_file_ids if allowed_file_ids is None or item in allowed_file_ids]
        subtree_faq_ids = [item for item in node.subtree_faq_ids if allowed_faq_ids is None or item in allowed_faq_ids]
        return direct_file_ids, direct_faq_ids, subtree_file_ids, subtree_faq_ids

    @classmethod
    def topic_summary_response(
        cls,
        node: CorpusNodeDocument,
        allowed_file_ids: set[str] | None = None,
        allowed_faq_ids: set[str] | None = None,
    ) -> CorpusTopicSummaryResponse:
        _, _, subtree_file_ids, subtree_faq_ids = cls._filtered_ids(node, allowed_file_ids, allowed_faq_ids)
        return CorpusTopicSummaryResponse(
            node_key=node.node_key,
            title=node.title,
            summary=node.summary,
            parent_key=node.parent_key,
            file_count=len(subtree_file_ids),
            faq_count=len(subtree_faq_ids),
        )

    @classmethod
    def topic_detail_response(
        cls,
        node: CorpusNodeDocument,
        file_payloads: dict[str, CorpusFileRefResponse] | None = None,
        faq_payloads: dict[str, CorpusFaqRefResponse] | None = None,
        allowed_file_ids: set[str] | None = None,
        allowed_faq_ids: set[str] | None = None,
    ) -> CorpusTopicDetailResponse:
        file_payloads = file_payloads or {}
        faq_payloads = faq_payloads or {}
        direct_file_ids, direct_faq_ids, _, _ = cls._filtered_ids(node, allowed_file_ids, allowed_faq_ids)
        summary = cls.topic_summary_response(node, allowed_file_ids, allowed_faq_ids)
        return CorpusTopicDetailResponse(
            **summary.model_dump(),
            child_keys=node.child_keys,
            direct_files=[file_payloads.get(file_id, CorpusFileRefResponse(id=file_id)) for file_id in direct_file_ids],
            direct_faqs=[faq_payloads.get(faq_id, CorpusFaqRefResponse(id=faq_id)) for faq_id in direct_faq_ids],
        )

    async def _load_payload_name_maps(
        self,
        nodes: list[CorpusNodeDocument],
        allowed_file_ids: set[str] | None = None,
        allowed_faq_ids: set[str] | None = None,
    ) -> tuple[dict[str, CorpusFileRefResponse], dict[str, CorpusFaqRefResponse]]:
        """Hydrate direct payload details in two batch queries for FE tree rendering."""
        from app.modules.files.services.file_service import get_file_service
        from app.modules.faq.services.faq_service import get_faq_service

        file_ids = list(dict.fromkeys(
            file_id
            for node in nodes
            for file_id in node.direct_file_ids
            if allowed_file_ids is None or file_id in allowed_file_ids
        ))
        faq_ids = list(dict.fromkeys(
            faq_id
            for node in nodes
            for faq_id in node.direct_faq_ids
            if allowed_faq_ids is None or faq_id in allowed_faq_ids
        ))
        file_svc = get_file_service()
        faq_svc = await get_faq_service()
        files, faqs = await asyncio.gather(
            file_svc.get_files_by_ids(file_ids),
            faq_svc.get_faqs_by_ids(faq_ids),
        )
        return (
            {
                str(file.id): CorpusFileRefResponse(
                    id=str(file.id),
                    name=file.display_name or file.original_filename or "",
                    metadata=(
                        FileMetadataResponse.from_model(file.custom_metadata)
                        if file.custom_metadata
                        else None
                    ),
                    lecturer_only=bool(file.lecturer_only),
                    updated_at=file.updated_at,
                )
                for file in files
            },
            {
                str(faq.id): CorpusFaqRefResponse(
                    id=str(faq.id),
                    name=faq.question or "",
                    metadata=FaqMetadataResponse.from_model(faq.metadata_filter),
                    lecturer_only=bool(faq.lecturer_only),
                    updated_at=faq.updated_at,
                )
                for faq in faqs
            },
        )

    async def get_stats(self) -> CorpusStatsResponse:
        nodes = await self.repo.get_all()
        root_nodes = [node for node in nodes if node.parent_key is None]
        return CorpusStatsResponse(
            total_nodes=len(nodes),
            total_root_nodes=len(root_nodes),
            total_direct_file_links=sum(len(node.direct_file_ids) for node in nodes),
            total_direct_faq_links=sum(len(node.direct_faq_ids) for node in nodes),
        )

    async def list_topics(self) -> CorpusTopicListResponse:
        nodes = await self.repo.get_all()
        return CorpusTopicListResponse(
            total=len(nodes),
            items=[self.topic_summary_response(node) for node in sorted(nodes, key=lambda node: node.node_key)],
        )

    async def get_topic(self, node_key: str) -> CorpusTopicDetailResponse:
        node = await self.repo.get_by_key(node_key)
        if not node:
            raise ValueError(f"Node '{node_key}' not found")
        file_payloads, faq_payloads = await self._load_payload_name_maps([node])
        return self.topic_detail_response(node, file_payloads, faq_payloads)

    async def build_tree(
        self,
        metadata_filter: Optional[dict] = None,
        lecturer_only: Optional[bool] = None,
    ) -> CorpusTreeResponse:
        nodes = await self.repo.get_all()
        filter_active = bool(metadata_filter) or lecturer_only is not None
        allowed_file_ids: set[str] | None = None
        allowed_faq_ids: set[str] | None = None
        if filter_active:
            allowed_file_ids, allowed_faq_ids = await self.fetch_allowed_ids(
                metadata_filter,
                "admin",
                lecturer_only=lecturer_only,
            )
        file_payloads, faq_payloads = await self._load_payload_name_maps(
            nodes,
            allowed_file_ids,
            allowed_faq_ids,
        )
        node_map = {node.node_key: node for node in nodes}
        response_map = {
            node.node_key: self.topic_detail_response(node, file_payloads, faq_payloads, allowed_file_ids, allowed_faq_ids)
            for node in nodes
        }

        def is_visible(key: str) -> bool:
            response = response_map.get(key)
            return bool(response and (not filter_active or response.file_count or response.faq_count))

        def build(key: str, seen: frozenset[str]) -> CorpusTreeNodeResponse:
            node = node_map.get(key)
            if not node or key in seen:
                return CorpusTreeNodeResponse(node_key=key, title="missing or cyclic reference")
            response = response_map[key]
            return CorpusTreeNodeResponse(
                node_key=response.node_key,
                title=response.title,
                summary=response.summary,
                file_count=response.file_count,
                faq_count=response.faq_count,
                direct_files=response.direct_files,
                direct_faqs=response.direct_faqs,
                children=[
                    build(child_key, seen | {key})
                    for child_key in sorted(node.child_keys)
                    if is_visible(child_key)
                ],
            )

        roots = [node for node in nodes if node.parent_key is None]
        visible_roots = [node for node in roots if is_visible(node.node_key)]
        return CorpusTreeResponse(
            total_nodes=sum(1 for node in nodes if is_visible(node.node_key)),
            total_root_nodes=len(visible_roots),
            tree=[build(node.node_key, frozenset()) for node in sorted(visible_roots, key=lambda node: node.node_key)],
        )

    async def create_topic(self, request: TopicCreateRequest) -> CorpusTopicDetailResponse:
        node_key = slugify_topic(request.slug)
        if not node_key:
            raise ValueError("slug invalid after slugification")
        if await self.repo.get_by_key(node_key):
            raise ValueError(f"Topic '{node_key}' already exists")
        if request.parent_key and not await self.repo.get_by_key(request.parent_key):
            raise ValueError(f"Parent '{request.parent_key}' not found")
        node = await self.repo.upsert_node(
            node_key,
            title=request.title,
            summary=request.summary,
            parent_key=request.parent_key,
        )
        return self.topic_detail_response(node)

    async def update_topic(self, node_key: str, request: TopicUpdateRequest) -> CorpusTopicDetailResponse:
        node = await self.repo.get_by_key(node_key)
        if not node:
            raise ValueError(f"Node '{node_key}' not found")
        old_parent = node.parent_key

        if request.title is not None:
            node.title = request.title
        if request.summary is not None:
            node.summary = request.summary
        if "parent_key" in request.model_fields_set and request.parent_key != node.parent_key:
            if request.parent_key and not await self.repo.get_by_key(request.parent_key):
                raise ValueError(f"Parent '{request.parent_key}' not found")
            if await would_create_cycle(self.repo, node_key, request.parent_key):
                raise ValueError(f"Setting parent '{request.parent_key}' for node '{node_key}' would create a cycle.")
            await self.repo._unlink_from_parent(node_key, node.parent_key)
            await self.repo._link_to_parent(node_key, request.parent_key)
            node.parent_key = request.parent_key

        await node.save()
        await self.repo.rebuild_node_and_ancestors(node_key)
        if old_parent and old_parent != node.parent_key:
            await self.repo.rebuild_node_and_ancestors(old_parent)
        if old_parent != node.parent_key:
            await self.repo.assert_integrity()
        return await self.get_topic(node_key)

    async def delete_topic(self, node_key: str) -> TopicDeleteResponse:
        deleted = await self.repo.delete_by_key(node_key)
        if not deleted:
            raise ValueError(f"Node '{node_key}' not found")
        return TopicDeleteResponse(node_key=node_key, deleted=True)

    async def fetch_allowed_ids(
        self,
        metadata_filter: Optional[dict],
        user_role: Optional[str],
        lecturer_only: Optional[bool] = None,
    ) -> tuple[set[str], set[str]]:
        """Fetch allowed file/FAQ payload IDs through domain services."""
        from app.modules.files.services.file_service import get_file_service
        from app.modules.faq.services.faq_service import get_faq_service

        file_svc = get_file_service()
        faq_svc = await get_faq_service()
        if lecturer_only is None:
            file_call = file_svc.find_ids_for_corpus(metadata_filter, user_role)
            faq_call = faq_svc.find_ids_for_corpus(metadata_filter, user_role)
        else:
            file_call = file_svc.find_ids_for_corpus(metadata_filter, user_role, lecturer_only)
            faq_call = faq_svc.find_ids_for_corpus(metadata_filter, user_role, lecturer_only)
        file_ids, faq_ids = await asyncio.gather(file_call, faq_call)
        return file_ids, faq_ids

    async def reindex_payload(self, payload_type: str, payload_id: str, node_keys: list[str]) -> list[str]:
        """Sync file/FAQ payload membership on corpus nodes."""
        node_keys = list(dict.fromkeys(node_keys))
        nodes = await self.repo.get_by_keys(node_keys)
        existing_keys = {node.node_key for node in nodes}
        missing_keys = [node_key for node_key in node_keys if node_key not in existing_keys]
        if missing_keys:
            raise ValueError(f"Unknown corpus node keys: {missing_keys}")

        current = await self.repo.get_nodes_containing_payload(payload_type, payload_id)
        old_keys = [n.node_key for n in current]
        add, remove = diff_links(old_keys, node_keys)

        for node_key in add:
            await self.repo.add_payload_link(node_key, payload_type, payload_id)
        for node_key in remove:
            await self.repo.remove_payload_link(node_key, payload_type, payload_id)
        logger.info(f"[Corpus] index {payload_type}:{payload_id}: +{add} -{remove}")
        return node_keys

    async def get_payload_node_keys(self, payload_type: str, payload_id: str) -> list[str]:
        """Return current direct topic assignments without hydrating the payload."""
        nodes = await self.repo.get_nodes_containing_payload(payload_type, payload_id)
        return sorted(node.node_key for node in nodes)

    async def existing_node_keys(self, node_keys: list[str]) -> list[str]:
        """Keep restore assignments whose topics still exist."""
        normalized = list(dict.fromkeys(node_keys))
        if not normalized:
            return []
        nodes = await self.repo.get_by_keys(normalized)
        existing = {node.node_key for node in nodes}
        return [node_key for node_key in normalized if node_key in existing]

    async def _get_payload_name(self, payload_type: str, payload_id: str) -> str:
        if payload_type == "file":
            from app.modules.files.services.file_service import get_file_service

            payload = await get_file_service().get_file_by_id(payload_id)
            if not payload:
                raise ValueError(f"File '{payload_id}' not found")
            return payload.display_name or payload.original_filename or ""

        from app.modules.faq.services.faq_service import get_faq_service

        payload = await (await get_faq_service()).get_faq(payload_id)
        if not payload:
            raise ValueError(f"FAQ '{payload_id}' not found")
        return payload.question or ""

    async def get_payload_topics(self, payload_type: str, payload_id: str) -> CorpusPayloadTopicsResponse:
        name = await self._get_payload_name(payload_type, payload_id)
        nodes = await self.repo.get_nodes_containing_payload(payload_type, payload_id)
        return CorpusPayloadTopicsResponse(
            payload_type=payload_type,
            payload_id=payload_id,
            name=name,
            node_keys=sorted(node.node_key for node in nodes),
        )

    async def update_payload_topics(
        self,
        payload_type: str,
        payload_id: str,
        node_keys: list[str],
    ) -> CorpusPayloadTopicsResponse:
        name = await self._get_payload_name(payload_type, payload_id)
        normalized_keys = list(dict.fromkeys(node_keys))
        await self.reindex_payload(payload_type, payload_id, normalized_keys)
        return CorpusPayloadTopicsResponse(
            payload_type=payload_type,
            payload_id=payload_id,
            name=name,
            node_keys=normalized_keys,
        )

    async def merge_topics(self, source_node_key: str, target_node_key: str) -> TopicMergeResponse:
        if source_node_key == target_node_key:
            raise ValueError("Source and target must differ")

        source = await self.repo.get_by_key(source_node_key)
        target = await self.repo.get_by_key(target_node_key)
        if not source:
            raise ValueError(f"Source '{source_node_key}' not found")
        if not target:
            raise ValueError(f"Target '{target_node_key}' not found")
        if await would_create_cycle(self.repo, source_node_key, target_node_key):
            raise ValueError(f"Cannot merge node '{source_node_key}' into descendant '{target_node_key}'")

        files_moved = 0
        for file_id in list(source.direct_file_ids):
            await self.repo.remove_payload_link(source_node_key, "file", file_id)
            await self.repo.add_payload_link(target_node_key, "file", file_id)
            files_moved += 1

        faqs_moved = 0
        for faq_id in list(source.direct_faq_ids):
            await self.repo.remove_payload_link(source_node_key, "faq", faq_id)
            await self.repo.add_payload_link(target_node_key, "faq", faq_id)
            faqs_moved += 1

        old_parent = source.parent_key
        children_moved = await self.repo.move_children(source_node_key, target_node_key)
        await self.repo.rebuild_node_and_ancestors(target_node_key)
        if old_parent:
            await self.repo.rebuild_node_and_ancestors(old_parent)
        await self.repo.delete_by_key(source_node_key)
        await self.repo.assert_integrity()
        return TopicMergeResponse(
            merged_from=source_node_key,
            merged_into=target_node_key,
            files_moved=files_moved,
            faqs_moved=faqs_moved,
            children_moved=children_moved,
            source_deleted=True,
        )

    async def backfill_corpus(self) -> None:
        from app.modules.faq.models.faq import FaqDocument
        from app.modules.files.models.file import FileDocument, FileStatus
        from app.modules.files.toc_tree.models.toc_tree import FileTocTree
        from app.modules.rag.ingestion.corpus_linker import get_corpus_linker
        repo = self.repo
        await repo.reset_all_links()
        logger.info("[Corpus][Backfill] cleared direct/subtree corpus links")

        corpus_linker = get_corpus_linker()
        files_ok = files_err = faqs_ok = faqs_err = 0
        batch_size = 100

        skip = 0
        while True:
            batch = await FileDocument.find({
                "status": FileStatus.READY.value,
                "deleted_at": None,
            }).skip(skip).limit(batch_size).to_list()
            if not batch:
                break
            for file_doc in batch:
                try:
                    toc_tree = await FileTocTree.find_one(FileTocTree.file_id == str(file_doc.id))
                    await corpus_linker.index_file(
                        str(file_doc.id),
                        display_name=file_doc.display_name or "",
                        doc_description=(toc_tree.doc_description if toc_tree else "") or "",
                        toc_headings=file_doc.table_of_contents or [],
                    )
                    files_ok += 1
                except Exception as exc:
                    logger.error("[Corpus][Backfill] index_file %s: %s", file_doc.id, exc)
                    files_err += 1
            skip += batch_size
            if len(batch) < batch_size:
                break

        skip = 0
        while True:
            batch = await FaqDocument.find({"deleted_at": None}).skip(skip).limit(batch_size).to_list()
            if not batch:
                break
            for faq in batch:
                try:
                    await corpus_linker.index_faq(
                        str(faq.id),
                        question=faq.question or "",
                        answer_markdown=faq.answer_markdown or "",
                    )
                    faqs_ok += 1
                except Exception as exc:
                    logger.error("[Corpus][Backfill] index_faq %s: %s", faq.id, exc)
                    faqs_err += 1
            skip += batch_size
            if len(batch) < batch_size:
                break

        logger.info(
            "[Corpus][Backfill] Done. Files %s/%s ok, FAQs %s/%s ok.",
            files_ok,
            files_ok + files_err,
            faqs_ok,
            faqs_ok + faqs_err,
        )
        await repo.assert_integrity()

    async def _unindex(self, payload_type: str, payload_id: str) -> None:
        nodes = await self.repo.get_nodes_containing_payload(payload_type, payload_id)
        for node in nodes:
            await self.repo.remove_payload_link(node.node_key, payload_type, payload_id)
        logger.info(f"[Corpus] unindex {payload_type}:{payload_id} (removed from {len(nodes)} nodes)")

    async def unindex_file(self, file_id: str) -> None:
        await self._unindex("file", file_id)

    async def unindex_faq(self, faq_id: str) -> None:
        await self._unindex("faq", faq_id)


_instance: Optional[CorpusService] = None


def get_corpus_service() -> CorpusService:
    global _instance
    if _instance is None:
        _instance = CorpusService()
    return _instance
