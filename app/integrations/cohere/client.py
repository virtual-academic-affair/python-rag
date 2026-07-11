from __future__ import annotations

import logging
from typing import Any, Optional

import cohere

from app.core.config import settings

logger = logging.getLogger(__name__)


class CohereRerankClient:
    """Thin integration wrapper around Cohere Rerank v2."""

    async def rerank(
        self,
        *,
        query: str,
        documents: list[str],
        top_n: int,
    ) -> Optional[list[int]]:
        if not self._enabled(query, documents):
            return None

        try:
            client = cohere.AsyncClientV2(
                api_key=settings.COHERE_API_KEY,
                timeout=settings.COHERE_RERANK_TIMEOUT_SECONDS,
            )
            response = await client.rerank(
                model=settings.COHERE_RERANK_MODEL,
                query=query,
                documents=documents,
                top_n=top_n,
                max_tokens_per_doc=settings.COHERE_RERANK_MAX_TOKENS_PER_DOC,
            )
        except Exception as exc:
            logger.warning("[CohereRerank] request failed, keeping original order: %s", exc)
            return None

        indexes = self._parse_indexes(
            response,
            expected_len=len(documents),
            expected_count=top_n,
        )
        if indexes is None:
            logger.warning("[CohereRerank] invalid response, keeping original order")
        return indexes

    @staticmethod
    def _enabled(query: str, documents: list[str]) -> bool:
        return (
            bool(settings.COHERE_RERANK_ENABLED)
            and bool(settings.COHERE_API_KEY)
            and bool(query and query.strip())
            and len(documents) > 1
        )

    @staticmethod
    def _parse_indexes(
        data: Any,
        *,
        expected_len: int,
        expected_count: int,
    ) -> Optional[list[int]]:
        results = getattr(data, "results", None)
        if results is None and isinstance(data, dict):
            results = data.get("results")
        if results is None:
            return None
        if not isinstance(results, list) or not results:
            return None

        indexes: list[int] = []
        seen: set[int] = set()
        for result in results:
            index = getattr(result, "index", None)
            if index is None and isinstance(result, dict):
                index = result.get("index")
            if not isinstance(index, int) or isinstance(index, bool):
                return None
            if index < 0 or index >= expected_len:
                return None
            if index in seen:
                return None
            seen.add(index)
            indexes.append(index)

        if len(indexes) != expected_count:
            return None
        return indexes


_cohere_rerank_client_instance: Optional[CohereRerankClient] = None


def get_cohere_rerank_client() -> CohereRerankClient:
    global _cohere_rerank_client_instance
    if _cohere_rerank_client_instance is None:
        _cohere_rerank_client_instance = CohereRerankClient()
    return _cohere_rerank_client_instance
