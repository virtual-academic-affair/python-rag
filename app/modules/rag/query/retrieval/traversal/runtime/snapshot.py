"""Filtered Corpus snapshot construction for one traversal session."""

from __future__ import annotations

import logging
from typing import Any

from app.modules.corpus.models.corpus_node import CorpusNodeDocument
from app.modules.corpus.repositories.corpus_node_repository import CorpusNodeRepository
from app.modules.rag.query.retrieval.traversal.contracts import (
    EligibleNodeCounts,
    FilteredCorpusSnapshot,
)

logger = logging.getLogger(__name__)


def _count_allowed(ids: list[str], allowed_ids: set[str]) -> int:
    return sum(item_id in allowed_ids for item_id in ids)


def build_filtered_snapshot_from_nodes(
    nodes: list[CorpusNodeDocument],
    allowed_file_ids: set[str],
    allowed_faq_ids: set[str],
    *,
    trace_id: str = "",
) -> FilteredCorpusSnapshot:
    """Build one consistent, query-scoped view of the existing Corpus model."""
    node_map = {node.node_key: node for node in nodes}
    counts_by_key: dict[str, EligibleNodeCounts] = {}
    visible_node_keys: set[str] = set()
    for node in nodes:
        counts = EligibleNodeCounts(
            direct_file_count=_count_allowed(node.direct_file_ids, allowed_file_ids),
            direct_faq_count=_count_allowed(node.direct_faq_ids, allowed_faq_ids),
            subtree_file_count=_count_allowed(node.subtree_file_ids, allowed_file_ids),
            subtree_faq_count=_count_allowed(node.subtree_faq_ids, allowed_faq_ids),
        )
        counts_by_key[node.node_key] = counts
        if counts.total_subtree_count:
            visible_node_keys.add(node.node_key)

    return FilteredCorpusSnapshot(
        node_map=node_map,
        counts_by_key=counts_by_key,
        visible_node_keys=visible_node_keys,
        visible_child_keys_by_parent={
            node.node_key: [key for key in node.child_keys if key in visible_node_keys]
            for node in nodes
            if node.node_key in visible_node_keys
        },
        visible_root_keys=[
            node.node_key
            for node in nodes
            if node.parent_key is None and node.node_key in visible_node_keys
        ],
        allowed_file_ids=allowed_file_ids,
        allowed_faq_ids=allowed_faq_ids,
        prefilter={
            "allowed_file_count": len(allowed_file_ids),
            "allowed_faq_count": len(allowed_faq_ids),
        },
        trace_id=trace_id,
    )


async def build_filtered_snapshot(
    repo: CorpusNodeRepository,
    corpus_service: Any,
    *,
    metadata_filter: dict | None,
    user_role: str | None,
    trace_id: str = "",
) -> FilteredCorpusSnapshot:
    """Create the complete query-scoped Corpus view, including authorization prefiltering."""
    logger.info(
        "[RAG][%s][snapshot.start] role=%s metadata=%s",
        trace_id,
        user_role,
        metadata_filter or {},
    )
    allowed_file_ids, allowed_faq_ids = await corpus_service.fetch_allowed_ids(
        metadata_filter,
        user_role,
    )
    nodes = await repo.get_all()
    snapshot = build_filtered_snapshot_from_nodes(
        nodes,
        allowed_file_ids,
        allowed_faq_ids,
        trace_id=trace_id,
    )
    logger.info(
        "[RAG][%s][snapshot.ready] nodes=%d visible_nodes=%d visible_roots=%d allowed_files=%d allowed_faqs=%d",
        trace_id,
        len(nodes),
        len(snapshot.visible_node_keys),
        len(snapshot.visible_root_keys),
        len(allowed_file_ids),
        len(allowed_faq_ids),
    )
    return snapshot
