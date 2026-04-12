"""
Retrieval Service - Layered RAG logic.
Combines Qdrant semantic search with PageIndex structural context.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.integrations.qdrant.client import get_qdrant_retrieval_service
from app.integrations.pageindex.client import get_page_index_client
from app.modules.metadata.utils.filter_builder import get_filter_builder
from app.modules.toc_tree.repository import FileTocTreeRepository

logger = logging.getLogger(__name__)

class RetrievalService:
    def __init__(self):
        self._qdrant = get_qdrant_retrieval_service()
        self._filter_builder = get_filter_builder()
        self._page_index = get_page_index_client()
        self._toc_repo = FileTocTreeRepository()

    @property
    def page_index(self):
        """Expose PageIndex client for Agent tools."""
        return self._page_index

    async def retrieve_candidate_files(
        self,
        query: str,
        metadata_filter: Optional[Dict[str, Any]] = None,
        user_role: str = "student",
        top_k_chunks: int = 30, # Increased for better document scoring
        max_files: int = 5,
    ) -> List[Dict[str, Any]]:
        """Unified helper to fetch relevant files using PageIndex Semantic Document Search algorithm."""
        qdrant_meta_filter = await self._filter_builder.build_qdrant_filter(
            metadata=metadata_filter or {},
            user_role=user_role
        )

        hits = await self._qdrant.retrieve(
            query=query,
            top_k=top_k_chunks,
            metadata_filter=qdrant_meta_filter,
            # user_role đã được xử lý bên trong filter_builder
        )

        if not hits:
            return []

        import math
        from collections import defaultdict

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

        # 3. Retrieve top documents
        doc_scores.sort(key=lambda x: x["doc_score"], reverse=True)
        top_docs = doc_scores[:max_files]

        for ctx in top_docs:
            toc_doc = await self._toc_repo.find_by_file_id(ctx["file_id"])
            ctx["doc_description"] = (toc_doc or {}).get("doc_description", "")

        return top_docs

_retrieval_service_instance: Optional[RetrievalService] = None

def get_retrieval_service() -> RetrievalService:
    global _retrieval_service_instance
    if _retrieval_service_instance is None:
        _retrieval_service_instance = RetrievalService()
    return _retrieval_service_instance
