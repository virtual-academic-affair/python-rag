from __future__ import annotations

import logging
from typing import Optional

from app.modules.corpus.dtos.traversal import TraversalResult
from app.modules.corpus.services.corpus_service import get_corpus_service
from app.modules.rag.query.retrieval.traversal.loop import run_corpus_traversal

logger = logging.getLogger(__name__)


async def run_corpus_traversal_pipeline(
    question: str,
    *,
    metadata_filter: Optional[dict] = None,
    user_role: Optional[str] = None,
) -> TraversalResult:
    """Run deterministic prefiltering, traversal, and candidate resolution."""
    corpus_svc = get_corpus_service()
    allowed_files, allowed_faqs = await corpus_svc.fetch_allowed_ids(
        metadata_filter,
        user_role,
    )

    prefilter_trace = {
        "allowed_files": len(allowed_files),
        "allowed_faqs": len(allowed_faqs),
    }

    if not allowed_files and not allowed_faqs:
        return TraversalResult(prefilter=prefilter_trace)

    selected_topic_keys, expand_stack = await run_corpus_traversal(
        question,
        corpus_svc.repo,
        allowed_files,
        allowed_faqs,
    )
    result = await corpus_svc.resolve_candidates(
        selected_topic_keys,
        allowed_files,
        allowed_faqs,
        traversal_order=expand_stack,
    )
    result.prefilter = prefilter_trace
    return result
