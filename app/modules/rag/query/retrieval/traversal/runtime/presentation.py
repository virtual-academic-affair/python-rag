"""Agent-facing serialization of filtered Corpus nodes."""

from __future__ import annotations

from typing import Any

from app.modules.rag.query.retrieval.traversal.contracts import FilteredCorpusSnapshot


def node_payload(snapshot: FilteredCorpusSnapshot, node_key: str) -> dict[str, Any]:
    """Serialize an authorized topic node for an LLM tool response."""
    node = snapshot.node_map[node_key]
    counts = snapshot.counts_by_key[node_key]
    return {
        "nodeKey": node.node_key,
        "title": node.title,
        "summary": node.summary,
        "counts": {
            "directFiles": counts.direct_file_count,
            "directFaqs": counts.direct_faq_count,
            "subtreeFiles": counts.subtree_file_count,
            "subtreeFaqs": counts.subtree_faq_count,
        },
        "visibleChildCount": len(snapshot.visible_child_keys_by_parent.get(node_key, [])),
    }
