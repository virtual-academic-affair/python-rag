from __future__ import annotations

from typing import Any, Callable, Optional, TypeVar

import yaml

from app.core.config import settings
from app.integrations.cohere import CohereRerankClient
from app.integrations.cohere import get_cohere_rerank_client

T = TypeVar("T")


class CohereReranker:
    """Rerank retrieval candidates with Cohere Rerank v2."""

    def __init__(self, client: Optional[CohereRerankClient] = None):
        self._client = client or get_cohere_rerank_client()

    async def rerank_files(
        self,
        question: str,
        candidates: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        return await self._rerank(
            question,
            candidates,
            document_builder=self._file_document,
        )

    async def rerank_faqs(
        self,
        question: str,
        faq_docs: list[Any],
        *,
        limit: int,
    ) -> list[Any]:
        ranked = await self._rerank(
            question,
            faq_docs,
            document_builder=self._faq_document,
            top_n=limit,
        )
        return ranked[:limit]

    async def _rerank(
        self,
        question: str,
        items: list[T],
        *,
        document_builder: Callable[[T], dict[str, Any]],
        top_n: int | None = None,
    ) -> list[T]:
        if not self._enabled(question, items):
            return items

        limited = items[: settings.COHERE_RERANK_MAX_CANDIDATES]
        tail = items[settings.COHERE_RERANK_MAX_CANDIDATES :]
        if not limited:
            return items

        requested_top_n = min(top_n or len(limited), len(limited))
        documents = [
            yaml.dump(document_builder(item), sort_keys=False, allow_unicode=True)
            for item in limited
        ]
        indexes = await self._client.rerank(
            query=question,
            documents=documents,
            top_n=requested_top_n,
        )
        if indexes is None:
            return items

        ranked = [limited[index] for index in indexes]
        if requested_top_n < len(limited):
            return ranked
        return ranked + tail

    @staticmethod
    def _enabled(question: str, items: list[Any]) -> bool:
        return (
            bool(settings.COHERE_RERANK_ENABLED)
            and bool(settings.COHERE_API_KEY)
            and bool(question and question.strip())
            and len(items) > 1
        )

    @staticmethod
    def _file_document(candidate: dict[str, Any]) -> dict[str, Any]:
        return {
            "type": "file",
            "name": candidate.get("file_name", ""),
            "description": candidate.get("doc_description", ""),
        }

    @staticmethod
    def _faq_document(faq: Any) -> dict[str, Any]:
        meta = getattr(faq, "metadata_filter", None)
        enrollment_year = meta.enrollment_year.model_dump() if meta and meta.enrollment_year else None
        academic_year = meta.academic_year.model_dump() if meta and meta.academic_year else None
        return {
            "type": "faq",
            "question": getattr(faq, "question", "") or "",
            "answer": getattr(faq, "answer_markdown", "") or "",
            "enrollment_year": enrollment_year,
            "academic_year": academic_year,
        }


_cohere_reranker_instance: Optional[CohereReranker] = None


def get_cohere_reranker() -> CohereReranker:
    global _cohere_reranker_instance
    if _cohere_reranker_instance is None:
        _cohere_reranker_instance = CohereReranker()
    return _cohere_reranker_instance
