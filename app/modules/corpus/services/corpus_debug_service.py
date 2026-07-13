"""Corpus debug/preview orchestration."""

from __future__ import annotations

from app.modules.corpus.dtos import (
    CorpusTraversalRequest,
    CorpusTraversalResponse,
)
from app.modules.rag.query.retrieval.traversal import run_corpus_traversal_pipeline


class CorpusDebugService:
    async def traverse(self, body: CorpusTraversalRequest) -> CorpusTraversalResponse:
        metadata_filter = body.normalized_metadata_filter()
        result = await run_corpus_traversal_pipeline(
            body.question,
            metadata_filter=metadata_filter or None,
            user_role=body.role,
        )
        return CorpusTraversalResponse.from_result(body, result)


_corpus_debug_service_instance: CorpusDebugService | None = None


def get_corpus_debug_service() -> CorpusDebugService:
    global _corpus_debug_service_instance
    if _corpus_debug_service_instance is None:
        _corpus_debug_service_instance = CorpusDebugService()
    return _corpus_debug_service_instance
