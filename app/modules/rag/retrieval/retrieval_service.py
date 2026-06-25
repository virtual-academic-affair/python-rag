"""
Retrieval Service - Layered RAG logic.
Combines Qdrant semantic search with PageIndex structural context.
"""

from __future__ import annotations

import logging
import math
import time
from collections import defaultdict
from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.integrations.qdrant.client import get_qdrant_retrieval_service
from app.integrations.pageindex.client import get_page_index_client
from app.modules.metadata.utils.filter_builder import get_filter_builder
from app.modules.files.models.file import FileStatus
from app.modules.files.toc_tree.models.toc_tree import serialize_toc_structure
from app.modules.files.toc_tree.repositories.toc_tree_repository import FileTocTreeRepository
from app.modules.files.repositories.file_repository import FileRepository

logger = logging.getLogger(__name__)

class RetrievalService:
    def __init__(self):
        self._qdrant = get_qdrant_retrieval_service()
        self._filter_builder = get_filter_builder()
        self._page_index = get_page_index_client()
        self._toc_repo = FileTocTreeRepository()
        self._file_repo = FileRepository()

    @property
    def page_index(self):
        """Expose PageIndex client for Agent tools."""
        return self._page_index

    async def retrieve_candidate_files(
        self,
        query: str,
        metadata_filter: Optional[Dict[str, Any]] = None,
        top_k_chunks: int = 30, # Increased for better document scoring
        max_files: int = 5,
    ) -> List[Dict[str, Any]]:
        """Unified helper to fetch relevant files using PageIndex Semantic Document Search algorithm."""
        qdrant_meta_filter = await self._filter_builder.build_qdrant_filter(
            metadata_filter=metadata_filter or {}
        )

        logger.info(f"[Retrieval] Bắt đầu semantic search cho query: '{query[:50]}...', filter: {qdrant_meta_filter}")
        
        start_qdrant = time.perf_counter()
        hits = await self._qdrant.retrieve(
            query=query,
            top_k=top_k_chunks,
            metadata_filter=qdrant_meta_filter,
        )
        qdrant_dur = time.perf_counter() - start_qdrant

        if not hits:
            logger.info(f"[Retrieval] Không tìm thấy dữ liệu vector nào cho query '{query}' (Qdrant duration: {qdrant_dur:.2f}s)")
            return []
            
        logger.info(f"[Retrieval] Đã quét được {len(hits)} chunks từ Qdrant trong {qdrant_dur:.2f}s. Đang tính điểm DocScore...")

        doc_info = {}
        doc_chunks = defaultdict(list)

        # 1. Group chunks by file_id
        for hit in hits:
            fid = hit["file_id"]
            if fid not in doc_info:
                doc_info[fid] = hit.get("file_name", "")
            doc_chunks[fid].append(hit.get("_retrieval_score", 0.0))

        # 2. Compute Document Score
        doc_scores = []
        for fid, scores in doc_chunks.items():
            N = len(scores)
            total_score = sum(scores)
            # PageIndex DocScore formula: sum(ChunkScore) / sqrt(N + 1)
            doc_score = total_score / math.sqrt(N + 1)
            doc_scores.append({
                "file_id": fid,
                "file_name": doc_info[fid],
                "doc_score": doc_score
            })

        # 3. Retrieve top documents based on score threshold (at least 1, at most max_files)
        doc_scores.sort(key=lambda x: x["doc_score"], reverse=True)
        
        # Filter candidate files by database status (must be READY)
        all_candidate_ids = [d["file_id"] for d in doc_scores]
        file_docs = await self._file_repo.find_by_ids(all_candidate_ids)
        ready_file_map = {str(f.id): f for f in file_docs if f.status == FileStatus.READY}
        
        ready_doc_scores = [d for d in doc_scores if d["file_id"] in ready_file_map]
        
        before_filter_log = [
            f"{d['file_name']} (id={d['file_id']}, score={d['doc_score']:.4f})"
            for d in ready_doc_scores
        ]
        logger.info(f"[Retrieval] Các tài liệu READY được quét: {before_filter_log}")
        
        threshold = settings.RETRIEVAL_MIN_DOC_SCORE
        filtered_docs = []
        for i, d in enumerate(ready_doc_scores):
            if d["doc_score"] >= threshold:
                filtered_docs.append(d)
                
        top_docs = filtered_docs[:max_files]
        
        after_filter_log = [
            f"{d['file_name']} (id={d['file_id']}, score={d['doc_score']:.4f})"
            for d in top_docs
        ]
        logger.info(f"[Retrieval] Lọc ra {len(top_docs)} tài liệu tốt nhất (Ngưỡng điểm >= {threshold}): {after_filter_log}")

        # 4. Enrich with descriptions and structure (Batch query)
        top_ids = [d["file_id"] for d in top_docs]
        toc_docs = await self._toc_repo.find_by_file_ids(top_ids)
        toc_map = {t.file_id: t for t in toc_docs}
        
        valid_top_docs = []
        for d in top_docs:
            fid = d["file_id"]
            toc_doc = toc_map.get(fid)
            d["doc_description"] = toc_doc.doc_description if toc_doc else ""
            d["structure"] = serialize_toc_structure(toc_doc.structure) if toc_doc else []
            d["markdown_storage_path"] = toc_doc.markdown_storage_path if toc_doc else ""
            
            f_doc = ready_file_map.get(fid)
            if f_doc:
                d["storage_path"] = f_doc.storage_path or ""
                # table_of_contents: pre-filtered flat list of headings (blacklist-cleaned)
                d["table_of_contents"] = f_doc.table_of_contents or []
            else:
                d["storage_path"] = ""
                d["table_of_contents"] = []
                
            # Filter out stale/incomplete documents
            if not d.get("storage_path"):
                logger.warning(f"[Retrieval] Bỏ qua tài liệu stale/không tồn tại storage_path cho file_id={fid}")
                continue
            if not d.get("markdown_storage_path"):
                logger.warning(f"[Retrieval] Bỏ qua tài liệu thiếu TOC/markdown artifact cho file_id={fid}")
                continue
                
            valid_top_docs.append(d)

        return valid_top_docs

_retrieval_service_instance: Optional[RetrievalService] = None

def get_retrieval_service() -> RetrievalService:
    global _retrieval_service_instance
    if _retrieval_service_instance is None:
        _retrieval_service_instance = RetrievalService()
    return _retrieval_service_instance
