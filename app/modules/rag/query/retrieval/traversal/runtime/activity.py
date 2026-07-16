"""Safe public activity steps derived from successful Corpus agent tool calls."""

from __future__ import annotations

from typing import Any

from app.modules.rag.query.retrieval.traversal.contracts import FilteredCorpusSnapshot


def build_traversal_activity_steps(
    snapshot: FilteredCorpusSnapshot,
    tool_name: str,
    result: dict[str, Any],
) -> list[dict[str, Any]]:
    """Map a successful agent tool result to minimal UI-safe traversal steps."""
    status = result.get("status")
    if tool_name == "expand_topic" and status == "ok":
        node_key = str(result.get("nodeKey") or "")
        node = snapshot.node_map.get(node_key)
        title = getattr(node, "title", "") or node_key
        return [{
            "type": "corpus_traversal",
            "action": "expand",
            "node_key": node_key,
            "content": f"Đã mở chủ đề {title}.",
        }]

    if tool_name == "inspect_topic" and status == "ok":
        node = result.get("node") or {}
        node_key = str(node.get("nodeKey") or "")
        title = node.get("title") or node_key or "đã chọn"
        return [{
            "type": "corpus_traversal",
            "action": "inspect",
            "node_key": node_key,
            "content": f"Đã kiểm tra chủ đề {title}.",
        }]

    if tool_name == "select_topics" and status == "selected":
        topics = [
            topic
            for topic in (result.get("selectedTopics") or [])
            if isinstance(topic, dict)
        ]
        node_keys = [str(topic.get("nodeKey") or "") for topic in topics if topic.get("nodeKey")]
        titles = [str(topic.get("nodeTitle") or topic.get("nodeKey")) for topic in topics]
        return [{
            "type": "corpus_traversal",
            "action": "select",
            "node_keys": node_keys,
            "content": f"Đã chọn các chủ đề: {', '.join(titles) or 'liên quan'}.",
        }]

    if tool_name == "select_no_match" and status == "no_match":
        return [{
            "type": "corpus_traversal",
            "action": "no_match",
            "content": "Không tìm thấy chủ đề phù hợp trong Corpus.",
        }]

    return []
