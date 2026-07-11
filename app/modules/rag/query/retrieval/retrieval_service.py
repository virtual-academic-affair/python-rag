"""
Retrieval Service - query RAG retrieval orchestration.
Runs corpus traversal, prepares minimal file candidates, fetches supporting FAQ,
and reranks context before handing it to chat/email answer generation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
from typing import Any, Optional

from app.core.config import settings
from app.core.exceptions import AppException
from app.modules.corpus.dtos.traversal import TraversalResult
from app.modules.rag.query.retrieval.hydration import hydrate_agent_file_candidates
from app.modules.rag.query.retrieval.hydration import fetch_supporting_faqs
from app.modules.rag.query.retrieval.rerank import get_cohere_reranker
from app.modules.rag.query.retrieval.traversal import run_corpus_traversal_pipeline

logger = logging.getLogger(__name__)

FAQ_CONTEXT_LIMIT = 3


@dataclass
class RetrievalContext:
    candidate_files: list[dict[str, Any]] = field(default_factory=list)
    faq_docs: list[Any] = field(default_factory=list)
    prefilter: Optional[dict] = None
    traversal_order: list[str] = field(default_factory=list)


class RetrievalService:
    def __init__(self):
        self._reranker = get_cohere_reranker()

    async def retrieve_context(
        self,
        question: str,
        *,
        metadata_filter: Optional[dict] = None,
        user_role: Optional[str] = None,
        max_files: int = 5,
    ) -> RetrievalContext:
        """Run traversal, hydrate/rerank file candidates, and hydrate supporting FAQs."""
        try:
            result = await run_corpus_traversal_pipeline(
                question,
                metadata_filter=metadata_filter,
                user_role=user_role,
            )
        except AppException:
            raise
        except Exception as e:
            logger.warning("[Retrieval] traverse failed (best-effort): %s", e)
            result = TraversalResult()

        candidate_files = await self._prepare_file_candidates(
            result.file_candidates,
            max_files=max_files,
            question=question,
        )
        faq_fetch_limit = max(settings.COHERE_RERANK_MAX_CANDIDATES, FAQ_CONTEXT_LIMIT)
        faq_docs = await fetch_supporting_faqs(result.supporting_faqs, limit=faq_fetch_limit)
        if faq_docs and question and question.strip():
            faq_docs = await self._reranker.rerank_faqs(
                question,
                faq_docs,
                limit=FAQ_CONTEXT_LIMIT,
            )
        else:
            faq_docs = faq_docs[:FAQ_CONTEXT_LIMIT]
        logger.info(
            "[Retrieval] context: %s files, %s supporting FAQs",
            len(candidate_files),
            len(faq_docs),
        )
        return RetrievalContext(
            candidate_files=candidate_files,
            faq_docs=faq_docs,
            prefilter=result.prefilter,
            traversal_order=result.traversal_order,
        )

    async def _prepare_file_candidates(
        self,
        candidates: list,  # list of Candidate dataclass instances from corpus.dtos.traversal
        max_files: int = 5,
        question: Optional[str] = None,
    ) -> list[dict]:
        """
        Convert corpus TraversalResult.file_candidates to the minimal
        candidate_files format expected by rerank and run_agent_loop.
        Metadata (khóa/năm học), quyền (lecturer_only), và READY status đã lọc
        ở pre-filter trước traversal — ở đây chỉ hydrate FileDocument + FileTocTree,
        rồi drop file thiếu storage path.

        Nếu question được cung cấp, thực hiện Cohere rerank. Khi rerank lỗi hoặc không
        có question, giữ nguyên thứ tự traversal.
        """
        if not candidates:
            return []

        id_order = [c.leaf_id for c in candidates]
        result = await hydrate_agent_file_candidates(id_order)

        if question and question.strip():
            result = await self._reranker.rerank_files(question, result)

        hydrated_count = len(result)
        dropped_count = len(candidates) - hydrated_count
        result = result[:max_files]
        logger.info(
            f"[Retrieval] prepare_file_candidates: {hydrated_count} hydrated, "
            f"{dropped_count} dropped (filtered/missing storage_path), "
            f"{len(result)} returned"
        )
        return result


_retrieval_service_instance: Optional[RetrievalService] = None


def get_retrieval_service() -> RetrievalService:
    global _retrieval_service_instance
    if _retrieval_service_instance is None:
        _retrieval_service_instance = RetrievalService()
    return _retrieval_service_instance
