"""
Retrieval Service - Vectorless RAG logic.
Hydrate file candidates (đã chọn bởi corpus traversal) với TOC/structure cho agent loop.
"""

from __future__ import annotations

import logging
from typing import Optional

from app.integrations.pageindex.client import get_page_index_client
from app.modules.files.models.file import FileStatus
from app.modules.files.toc_tree.models.toc_tree import serialize_toc_structure
from app.modules.files.toc_tree.repositories.toc_tree_repository import FileTocTreeRepository
from app.modules.files.repositories.file_repository import FileRepository

logger = logging.getLogger(__name__)

class RetrievalService:
    def __init__(self):
        self._page_index = get_page_index_client()
        self._toc_repo = FileTocTreeRepository()
        self._file_repo = FileRepository()

    @property
    def page_index(self):
        """Expose PageIndex client for Agent tools."""
        return self._page_index

    async def enrich_corpus_candidates(
        self,
        candidates: list,  # list of Candidate dataclass instances from corpus.dtos.traversal
        max_files: int = 5,
    ) -> list[dict]:
        """
        Convert corpus TraversalResult.file_candidates to candidate_files format
        expected by run_agent_loop.
        Metadata (khóa/năm học) + quyền (lecturer_only) đã lọc ở pre-filter trước
        traversal — ở đây chỉ hydrate FileDocument (status=ready) + FileTocTree,
        drop file thiếu storage path.
        Giữ thứ tự candidates từ traversal, cắt tại max_files sau khi lọc.
        """
        from bson import ObjectId

        if not candidates:
            return []

        id_order = [c.leaf_id for c in candidates]
        valid_ids = []
        for c in candidates:
            try:
                valid_ids.append(ObjectId(c.leaf_id))
            except Exception:
                pass

        if not valid_ids:
            return []

        query: dict = {"_id": {"$in": valid_ids}, "status": FileStatus.READY.value}

        files, _ = await self._file_repo.list_files(
            query,
            skip=0,
            limit=len(valid_ids) + 1,
        )
        if not files:
            return []

        file_ids_str = [str(f.id) for f in files]
        toc_docs = await self._toc_repo.find_by_file_ids(file_ids_str)
        toc_map = {t.file_id: t for t in toc_docs}

        result = []
        for f in files:
            fid = str(f.id)
            toc = toc_map.get(fid)
            storage_path = f.storage_path or ""
            markdown_storage_path = (toc.markdown_storage_path if toc else "") or ""
            if not storage_path or not markdown_storage_path:
                continue
            result.append({
                "file_id": fid,
                "file_name": f.display_name or "",
                "nav_reason": "corpus_traversal",
                "doc_description": (toc.doc_description if toc else "") or "",
                "structure": serialize_toc_structure(toc.structure) if toc else [],
                "markdown_storage_path": markdown_storage_path,
                "storage_path": storage_path,
                "table_of_contents": f.table_of_contents or [],
            })

        # Giữ thứ tự candidates từ traversal (ổn định), cắt tại max_files
        order = {fid: i for i, fid in enumerate(id_order)}
        result.sort(key=lambda x: order.get(x["file_id"], len(order)))
        dropped = len(candidates) - len(result)
        result = result[:max_files]
        logger.info(
            f"[Corpus] enrich_corpus_candidates: {len(result)} enriched, "
            f"{dropped} dropped (filtered/missing storage_path)"
        )
        return result


_retrieval_service_instance: Optional[RetrievalService] = None

def get_retrieval_service() -> RetrievalService:
    global _retrieval_service_instance
    if _retrieval_service_instance is None:
        _retrieval_service_instance = RetrievalService()
    return _retrieval_service_instance
