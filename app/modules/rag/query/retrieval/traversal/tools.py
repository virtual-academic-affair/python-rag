from __future__ import annotations

import logging
from typing import Any

from app.integrations.llm.contracts import LLMTool
from app.modules.rag.query.retrieval.traversal.contracts import TraversalSession
from app.modules.rag.query.retrieval.traversal.runtime.inspection import inspect_samples
from app.modules.rag.query.retrieval.traversal.runtime.presentation import node_payload
from app.modules.rag.query.retrieval.traversal.runtime.selection import select_topics as validate_and_select_topics

logger = logging.getLogger(__name__)


def build_traversal_tools(
    session: TraversalSession,
    *,
    include_reasoning: bool = False,
) -> list[LLMTool]:
    """Build the agent-callable Corpus traversal tools for one session."""

    async def _expand_topic(node_key: str) -> dict[str, Any]:
        if node_key not in session.revealed_node_keys:
            return {"status": "invalid", "reason": "node_key was not revealed by this traversal"}
        child_keys = session.snapshot.visible_child_keys_by_parent.get(node_key, [])
        session.revealed_node_keys.update(child_keys)
        if node_key not in session.expanded_node_keys:
            session.expanded_node_keys.append(node_key)
        logger.info("[RAG][%s][traversal.tool.expand] node=%s children=%s", session.snapshot.trace_id, node_key, child_keys)
        return {
            "status": "ok",
            "nodeKey": node_key,
            "topics": [node_payload(session.snapshot, key) for key in child_keys],
        }

    async def _inspect_topic(
        node_key: str,
        scope: str = "subtree",
    ) -> dict[str, Any]:
        if node_key not in session.revealed_node_keys:
            return {"status": "invalid", "reason": "node_key was not revealed by this traversal"}
        if scope not in {"direct", "subtree"}:
            return {"status": "invalid", "reason": "scope must be direct or subtree"}
        node = session.snapshot.node_map[node_key]
        if node_key not in session.inspected_node_keys:
            session.inspected_node_keys.append(node_key)
        logger.info("[RAG][%s][traversal.tool.inspect] node=%s scope=%s", session.snapshot.trace_id, node_key, scope)
        samples = await inspect_samples(session, node, scope)
        return {"status": "ok", "node": node_payload(session.snapshot, node_key), "scope": scope, **samples}

    async def _select_topics(selections: list[dict[str, Any]]) -> dict[str, Any]:
        result = validate_and_select_topics(session, selections)
        logger.info("[RAG][%s][traversal.tool.select] selections=%s status=%s files=%s faqs=%s reason=%s", session.snapshot.trace_id, selections, result.get("status"), result.get("totalFileCandidates"), result.get("totalFaqCandidates"), result.get("reason"))
        return result

    if include_reasoning:
        async def expand_topic(node_key: str, reasoning: str) -> dict[str, Any]:
            """Reveal one child level. reasoning must be one short Vietnamese sentence."""
            return await _expand_topic(node_key)

        async def inspect_topic(
            node_key: str,
            reasoning: str,
            scope: str = "subtree",
        ) -> dict[str, Any]:
            """Inspect authorized samples. reasoning must be one short Vietnamese sentence."""
            return await _inspect_topic(node_key, scope)

        async def select_topics(
            selections: list[dict[str, Any]],
            reasoning: str,
        ) -> dict[str, Any]:
            """Finalize topic selections. reasoning must be one short Vietnamese sentence."""
            return await _select_topics(selections)
    else:
        async def expand_topic(node_key: str) -> dict[str, Any]:
            """Reveal immediate eligible children of a previously returned topic."""
            return await _expand_topic(node_key)

        async def inspect_topic(
            node_key: str,
            scope: str = "subtree",
        ) -> dict[str, Any]:
            """Inspect eligible file and FAQ samples from a revealed topic."""
            return await _inspect_topic(node_key, scope)

        async def select_topics(selections: list[dict[str, Any]]) -> dict[str, Any]:
            """Finalize revealed topics using direct or subtree payload scope."""
            return await _select_topics(selections)

    async def select_no_match(reason: str) -> dict[str, Any]:
        """Explicitly end traversal only when no revealed topic can answer the question."""
        logger.info("[RAG][%s][traversal.tool.no_match] reason=%r", session.snapshot.trace_id, str(reason)[:300])
        return {"status": "no_match", "reason": str(reason or "agent found no relevant topic")}

    reasoning_property = {
        "reasoning": {
            "type": "string",
            "description": "One short Vietnamese sentence, at most 500 characters, explaining the current decision.",
        }
    } if include_reasoning else {}
    reasoning_required = ["reasoning"] if include_reasoning else []

    return [
        LLMTool(
            name="expand_topic",
            description="Reveal one child level of a previously returned topic.",
            parameters={
                "type": "object",
                "properties": {
                    "node_key": {"type": "string"},
                    **reasoning_property,
                },
                "required": ["node_key", *reasoning_required],
                "additionalProperties": False,
            },
            handler=expand_topic,
        ),
        LLMTool(
            name="inspect_topic",
            description="Inspect authorized file and FAQ samples for a previously returned topic.",
            parameters={
                "type": "object",
                "properties": {
                    "node_key": {"type": "string"},
                    "scope": {"type": "string", "enum": ["direct", "subtree"]},
                    **reasoning_property,
                },
                "required": ["node_key", *reasoning_required],
                "additionalProperties": False,
            },
            handler=inspect_topic,
        ),
        LLMTool(
            name="select_topics",
            description="Finish traversal by selecting the relevant revealed topics.",
            parameters={
                "type": "object",
                "properties": {
                    "selections": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "node_key": {"type": "string"},
                                "scope": {"type": "string", "enum": ["direct", "subtree"]},
                            },
                            "required": ["node_key", "scope"],
                            "additionalProperties": False,
                        },
                    },
                    **reasoning_property,
                },
                "required": ["selections", *reasoning_required],
                "additionalProperties": False,
            },
            handler=select_topics,
        ),
        LLMTool(
            name="select_no_match",
            description="Finish traversal when none of the revealed topics is relevant.",
            parameters={
                "type": "object",
                "properties": {
                    "reason": {"type": "string"},
                },
                "required": ["reason"],
                "additionalProperties": False,
            },
            handler=select_no_match,
        ),
    ]
