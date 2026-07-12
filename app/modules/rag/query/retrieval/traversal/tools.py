from __future__ import annotations

import logging
from typing import Any, Callable

from app.core.config import settings
from app.modules.rag.query.retrieval.traversal.contracts import FilteredCorpusSnapshot, TraversalSession
from app.modules.rag.query.retrieval.traversal.runtime.inspection import inspect_samples
from app.modules.rag.query.retrieval.traversal.runtime.presentation import node_payload
from app.modules.rag.query.retrieval.traversal.runtime.selection import select_topics as validate_and_select_topics

logger = logging.getLogger(__name__)


def build_traversal_tools(snapshot: FilteredCorpusSnapshot) -> list[Callable]:
    """Build only the agent-callable Corpus traversal tools for one snapshot."""
    session: TraversalSession | None = None

    async def _session() -> TraversalSession:
        nonlocal session
        if session is None:
            session = TraversalSession(snapshot=snapshot)
        return session

    async def list_root_topics() -> dict[str, Any]:
        """List eligible root topics. This must be the first traversal tool call."""
        active = await _session()
        active.roots_listed = True
        active.revealed_node_keys.update(active.snapshot.visible_root_keys)
        logger.info("[RAG][%s][traversal.tool.list_roots] roots=%s", active.snapshot.trace_id, active.snapshot.visible_root_keys)
        return {
            "status": "ok",
            "topics": [node_payload(active.snapshot, key) for key in active.snapshot.visible_root_keys],
        }

    async def expand_topic(node_key: str) -> dict[str, Any]:
        """Reveal immediate eligible children of a topic previously returned by a tool."""
        active = await _session()
        if node_key not in active.revealed_node_keys:
            return {"status": "invalid", "reason": "node_key was not revealed by this traversal"}
        child_keys = active.snapshot.visible_child_keys_by_parent.get(node_key, [])
        active.revealed_node_keys.update(child_keys)
        if node_key not in active.expanded_node_keys:
            active.expanded_node_keys.append(node_key)
        logger.info("[RAG][%s][traversal.tool.expand] node=%s children=%s", active.snapshot.trace_id, node_key, child_keys)
        return {
            "status": "ok",
            "nodeKey": node_key,
            "topics": [node_payload(active.snapshot, key) for key in child_keys],
        }

    async def inspect_topic(
        node_key: str,
        scope: str = "subtree",
        sample_limit: int = settings.CORPUS_TRAVERSAL_TOPIC_SAMPLE_LIMIT,
    ) -> dict[str, Any]:
        """Inspect eligible sample files and FAQs from a previously revealed topic."""
        active = await _session()
        if node_key not in active.revealed_node_keys:
            return {"status": "invalid", "reason": "node_key was not revealed by this traversal"}
        if scope not in {"direct", "subtree"}:
            return {"status": "invalid", "reason": "scope must be direct or subtree"}
        if not isinstance(sample_limit, int) or sample_limit < 1:
            return {"status": "invalid", "reason": "sample_limit must be a positive integer"}
        node = active.snapshot.node_map[node_key]
        if node_key not in active.inspected_node_keys:
            active.inspected_node_keys.append(node_key)
        logger.info("[RAG][%s][traversal.tool.inspect] node=%s scope=%s sample_limit=%d", active.snapshot.trace_id, node_key, scope, sample_limit)
        samples = await inspect_samples(active, node, scope, min(sample_limit, settings.CORPUS_TRAVERSAL_TOPIC_SAMPLE_LIMIT))
        return {"status": "ok", "node": node_payload(active.snapshot, node_key), "scope": scope, **samples}

    async def select_topics(selections: list[dict[str, Any]]) -> dict[str, Any]:
        """Finalize revealed topics using direct or subtree payload scope."""
        active = await _session()
        result = validate_and_select_topics(active, selections)
        logger.info("[RAG][%s][traversal.tool.select] selections=%s status=%s files=%s faqs=%s reason=%s", active.snapshot.trace_id, selections, result.get("status"), result.get("totalFileCandidates"), result.get("totalFaqCandidates"), result.get("reason"))
        return result

    async def select_no_match(reason: str) -> dict[str, Any]:
        """Explicitly end traversal only when no revealed topic can answer the question."""
        active = await _session()
        if not active.roots_listed:
            return {"status": "invalid", "reason": "list_root_topics must be called before no-match selection"}
        logger.info("[RAG][%s][traversal.tool.no_match] reason=%r", active.snapshot.trace_id, str(reason)[:300])
        return {"status": "no_match", "reason": str(reason or "agent found no relevant topic")}

    list_root_topics._get_session = _session
    return [list_root_topics, expand_topic, inspect_topic, select_topics, select_no_match]
