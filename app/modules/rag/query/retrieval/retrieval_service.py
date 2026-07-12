"""
Retrieval Service - query RAG retrieval orchestration.
Runs corpus traversal, prepares minimal file candidates, fetches FAQ candidates,
and reranks context before handing it to chat/email answer generation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
from collections.abc import Awaitable, Callable
from typing import Any, Optional

from app.core.config import settings
from app.modules.rag.query.retrieval.hydration import hydrate_pageindex_candidate_files
from app.modules.rag.query.retrieval.hydration import hydrate_faq_candidate_docs
from app.modules.rag.query.retrieval.rerank import get_cohere_reranker
from app.modules.rag.query.retrieval.traversal import run_corpus_traversal_pipeline

logger = logging.getLogger(__name__)

FAQ_CONTEXT_LIMIT = 3


@dataclass
class RetrievalSeeds:
    file_candidates: list[Any] = field(default_factory=list)
    faq_candidates: list[Any] = field(default_factory=list)
    prefilter: Optional[dict] = None
    traversal_node_keys: list[str] = field(default_factory=list)
    traversal_steps: list[dict[str, Any]] = field(default_factory=list)


class RetrievalService:
    def __init__(self):
        self._reranker = get_cohere_reranker()

    async def traverse_query(
        self,
        question: str,
        *,
        metadata_filter: Optional[dict] = None,
        user_role: Optional[str] = None,
        trace_id: str = "",
        on_traversal_step: Callable[[dict], Awaitable[None]] | None = None,
    ) -> RetrievalSeeds:
        """Run corpus traversal and return raw file/FAQ candidate seeds."""
        result = await run_corpus_traversal_pipeline(
            question,
            metadata_filter=metadata_filter,
            user_role=user_role,
            trace_id=trace_id,
            on_step=on_traversal_step,
        )
        logger.info(
            "[RAG][%s][retrieval.seeds] prefilter=%s traversal_status=%s files=%d faqs=%d expanded=%s",
            trace_id,
            result.prefilter,
            result.status,
            len(result.file_candidates),
            len(result.faq_candidates),
            result.traversal_node_keys,
        )
        return RetrievalSeeds(
            file_candidates=result.file_candidates,
            faq_candidates=result.faq_candidates,
            prefilter=result.prefilter,
            traversal_node_keys=result.traversal_node_keys,
            traversal_steps=result.steps,
        )

    async def retrieve_faq_context(
        self,
        question: str,
        faq_candidates: list[Any],
        *,
        trace_id: str = "",
    ) -> list[Any]:
        """Hydrate and rerank FAQ candidates before attempting direct FAQ answering."""
        faq_fetch_limit = max(settings.COHERE_RERANK_MAX_CANDIDATES, FAQ_CONTEXT_LIMIT)
        faq_docs = await hydrate_faq_candidate_docs(faq_candidates, limit=faq_fetch_limit)
        if faq_docs and question and question.strip():
            faq_docs = await self._reranker.rerank_faqs(
                question,
                faq_docs,
                limit=FAQ_CONTEXT_LIMIT,
            )
        else:
            faq_docs = faq_docs[:FAQ_CONTEXT_LIMIT]
        logger.info(
            "[RAG][%s][retrieval.faq] seeds=%d hydrated_and_ranked=%d faq_ids=%s",
            trace_id,
            len(faq_candidates),
            len(faq_docs),
            [str(getattr(faq, "id", "")) for faq in faq_docs],
        )
        return faq_docs

    async def retrieve_file_context(
        self,
        question: str,
        file_candidates: list[Any],
        *,
        max_files: int = 5,
        trace_id: str = "",
    ) -> list[dict]:
        """Hydrate and rerank PageIndex file candidates."""
        candidate_files = await self._prepare_file_candidates(
            file_candidates,
            max_files=max_files,
            question=question,
            trace_id=trace_id,
        )
        logger.info(
            "[RAG][%s][retrieval.files] seeds=%d selected=%d file_ids=%s",
            trace_id,
            len(file_candidates),
            len(candidate_files),
            [file.get("file_id") for file in candidate_files],
        )
        return candidate_files

    async def _prepare_file_candidates(
        self,
        candidates: list,  # list of FileCandidate dataclass instances from corpus.contracts
        max_files: int = 5,
        question: Optional[str] = None,
        trace_id: str = "",
    ) -> list[dict]:
        """
        Convert corpus TraversalResult.file_candidates to the minimal
        candidate_files format expected by rerank and PageIndex agent loop.
        Metadata (khóa/năm học), quyền lecture-only, và READY status đã lọc
        ở pre-filter trước traversal — ở đây chỉ hydrate FileDocument + FileTocTree,
        rồi drop file thiếu storage path.

        Nếu question được cung cấp, thực hiện Cohere rerank. Khi rerank lỗi hoặc không
        có question, giữ nguyên thứ tự traversal.
        """
        if not candidates:
            return []

        id_order = [c.file_id for c in candidates]
        result = await hydrate_pageindex_candidate_files(id_order)

        if question and question.strip():
            result = await self._reranker.rerank_files(
                question,
                result,
                limit=max_files,
            )

        hydrated_count = len(result)
        dropped_count = len(candidates) - hydrated_count
        result = result[:max_files]
        logger.info(
            "[RAG][%s][retrieval.file_prepare] seeds=%d hydrated=%d dropped=%d reranked=%s returned=%d",
            trace_id,
            len(candidates),
            hydrated_count,
            dropped_count,
            bool(question and question.strip()),
            len(result),
        )
        return result


_retrieval_service_instance: Optional[RetrievalService] = None


def get_retrieval_service() -> RetrievalService:
    global _retrieval_service_instance
    if _retrieval_service_instance is None:
        _retrieval_service_instance = RetrievalService()
    return _retrieval_service_instance
