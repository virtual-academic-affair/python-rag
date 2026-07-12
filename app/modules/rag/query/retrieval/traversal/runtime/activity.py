"""Safe public activity steps derived from successful Corpus agent tool calls."""

from __future__ import annotations

from typing import Any

from app.modules.rag.query.retrieval.traversal.contracts import FilteredCorpusSnapshot


def build_traversal_activity_step(
    snapshot: FilteredCorpusSnapshot,
    tool_name: str,
    result: dict[str, Any],
) -> dict[str, Any] | None:
    """Map a successful agent tool result to a UI-safe traversal step."""
    status = result.get("status")
    if tool_name == "list_root_topics" and status == "ok":
        return {
            "type": "corpus_traversal",
            "action": "list_roots",
            "topic_count": len(result.get("topics") or []),
        }

    if tool_name == "expand_topic" and status == "ok":
        node_key = str(result.get("nodeKey") or "")
        node = snapshot.node_map.get(node_key)
        return {
            "type": "corpus_traversal",
            "action": "expand",
            "node_title": getattr(node, "title", node_key),
            "child_count": len(result.get("topics") or []),
        }

    if tool_name == "inspect_topic" and status == "ok":
        node = result.get("node") or {}
        return {
            "type": "corpus_traversal",
            "action": "inspect",
            "node_title": node.get("title") or node.get("nodeKey") or "chủ đề đã chọn",
            "scope": result.get("scope") or "subtree",
            "sample_file_count": len(result.get("sampleFiles") or []),
            "sample_faq_count": len(result.get("sampleFaqs") or []),
        }

    if tool_name == "select_topics" and status == "selected":
        return {
            "type": "corpus_traversal",
            "action": "select",
            "topics": result.get("selectedTopics") or [],
            "file_count": int(result.get("totalFileCandidates") or 0),
            "faq_count": int(result.get("totalFaqCandidates") or 0),
        }

    if tool_name == "select_no_match" and status == "no_match":
        return {"type": "corpus_traversal", "action": "no_match"}

    return None
