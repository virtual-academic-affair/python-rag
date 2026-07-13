from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Optional

from app.modules.corpus.contracts import TraversalResult
from app.modules.corpus.services.corpus_service import get_corpus_service
from app.modules.rag.query.retrieval.traversal.loop import run_corpus_traversal
from app.modules.rag.query.retrieval.traversal.runtime.snapshot import build_filtered_snapshot

logger = logging.getLogger(__name__)


async def run_corpus_traversal_pipeline(
    question: str,
    *,
    metadata_filter: Optional[dict] = None,
    user_role: Optional[str] = None,
    trace_id: str = "",
    on_step: Callable[[dict], Awaitable[None]] | None = None,
) -> TraversalResult:
    """Run deterministic prefiltering, traversal, and candidate resolution."""
    corpus_svc = get_corpus_service()
    snapshot = await build_filtered_snapshot(
        corpus_svc.repo,
        corpus_svc,
        metadata_filter=metadata_filter,
        user_role=user_role,
        trace_id=trace_id,
    )

    if not snapshot.allowed_file_ids and not snapshot.allowed_faq_ids:
        logger.info("[RAG][%s][traversal.prefilter_empty]", trace_id)
        return TraversalResult(
            status="no_match",
            termination_reason="prefilter_empty",
            prefilter=snapshot.prefilter,
        )

    traversal_kwargs = {"trace_id": trace_id}
    if on_step is not None:
        traversal_kwargs["on_step"] = on_step
    result = await run_corpus_traversal(question, snapshot, **traversal_kwargs)
    result.prefilter = snapshot.prefilter
    logger.info(
        "[RAG][%s][traversal.complete] status=%s topics=%s expanded=%s inspected=%s files=%d faqs=%d turns=%d reason=%s",
        trace_id,
        result.status,
        [f"{item.node_key}:{item.scope}" for item in result.selected_topics],
        result.expanded_node_keys,
        result.inspected_node_keys,
        len(result.file_candidates),
        len(result.faq_candidates),
        result.turn_count,
        result.termination_reason,
    )
    return result
