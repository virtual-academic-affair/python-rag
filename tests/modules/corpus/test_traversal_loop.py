from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from google.genai import types

from app.core.exceptions import CorpusTraversalError
from app.modules.corpus.models.corpus_node import CorpusNodeDocument
from app.modules.rag.query.retrieval.traversal.loop import run_corpus_traversal
from app.modules.rag.query.retrieval.traversal.runtime.snapshot import build_filtered_snapshot_from_nodes


def _make_node(node_key, file_ids=None, child_keys=None, parent_key=None):
    node = MagicMock(spec=CorpusNodeDocument)
    node.node_key = node_key
    node.title = node_key
    node.summary = ""
    node.direct_file_ids = file_ids or []
    node.direct_faq_ids = []
    node.subtree_file_ids = file_ids or []
    node.subtree_faq_ids = []
    node.child_keys = child_keys or []
    node.parent_key = parent_key
    return node


def _tool_call_response(name: str, args: dict):
    part = types.Part.from_function_call(name=name, args=args)
    return SimpleNamespace(candidates=[SimpleNamespace(content=types.Content(role="model", parts=[part]))])


@pytest.mark.asyncio
async def test_run_corpus_traversal_requires_explicit_valid_selection():
    valid = _make_node("valid-topic", file_ids=["file-ok"])
    snapshot = build_filtered_snapshot_from_nodes([valid], {"file-ok"}, set())
    responses = [
        _tool_call_response("list_root_topics", {}),
        _tool_call_response("select_topics", {"selections": [{"node_key": "valid-topic", "scope": "subtree"}]}),
    ]
    with patch("app.modules.rag.query.retrieval.traversal.loop.async_retry", AsyncMock(side_effect=responses)):
        result = await run_corpus_traversal("Câu hỏi", snapshot)

    assert result.status == "selected"
    assert [candidate.file_id for candidate in result.file_candidates] == ["file-ok"]
    assert result.turn_count == 2
    assert [step["action"] for step in result.steps] == ["list_roots", "select"]


@pytest.mark.asyncio
async def test_run_corpus_traversal_omits_invalid_tool_attempt_from_public_steps():
    valid = _make_node("valid-topic", file_ids=["file-ok"])
    snapshot = build_filtered_snapshot_from_nodes([valid], {"file-ok"}, set())
    responses = [
        _tool_call_response("expand_topic", {"node_key": "valid-topic"}),
        _tool_call_response("list_root_topics", {}),
        _tool_call_response("select_topics", {"selections": [{"node_key": "valid-topic", "scope": "subtree"}]}),
    ]
    with patch("app.modules.rag.query.retrieval.traversal.loop.async_retry", AsyncMock(side_effect=responses)):
        result = await run_corpus_traversal("Câu hỏi", snapshot)

    assert result.status == "selected"
    assert [step["action"] for step in result.steps] == ["list_roots", "select"]


@pytest.mark.asyncio
async def test_run_corpus_traversal_records_explicit_no_match_step():
    valid = _make_node("valid-topic", file_ids=["file-ok"])
    snapshot = build_filtered_snapshot_from_nodes([valid], {"file-ok"}, set())
    responses = [
        _tool_call_response("list_root_topics", {}),
        _tool_call_response("select_no_match", {"reason": "Không phù hợp"}),
    ]
    with patch("app.modules.rag.query.retrieval.traversal.loop.async_retry", AsyncMock(side_effect=responses)):
        result = await run_corpus_traversal("Câu hỏi", snapshot)

    assert result.status == "no_match"
    assert [step["action"] for step in result.steps] == ["list_roots", "no_match"]


@pytest.mark.asyncio
async def test_run_corpus_traversal_llm_failure_raises_app_exception():
    snapshot = build_filtered_snapshot_from_nodes([], {"file-ok"}, set())
    with patch("app.modules.rag.query.retrieval.traversal.loop.async_retry", AsyncMock(side_effect=RuntimeError("gemini down"))):
        with pytest.raises(CorpusTraversalError) as exc:
            await run_corpus_traversal("Câu hỏi", snapshot)
    assert exc.value.status_code == 502


@pytest.mark.asyncio
async def test_run_corpus_traversal_no_tool_call_is_failure():
    snapshot = build_filtered_snapshot_from_nodes([], {"file-ok"}, set())
    response = SimpleNamespace(candidates=[SimpleNamespace(content=types.Content(role="model", parts=[types.Part.from_text(text="done")]))])
    with patch("app.modules.rag.query.retrieval.traversal.loop.async_retry", AsyncMock(return_value=response)):
        with pytest.raises(CorpusTraversalError, match="without explicit selection"):
            await run_corpus_traversal("Câu hỏi", snapshot)


@pytest.mark.asyncio
async def test_run_corpus_traversal_max_turns_returns_no_match():
    valid = _make_node("valid-topic", file_ids=["file-ok"])
    snapshot = build_filtered_snapshot_from_nodes([valid], {"file-ok"}, set())
    responses = [
        _tool_call_response("list_root_topics", {}),
        _tool_call_response("list_root_topics", {}),
    ]
    with patch("app.modules.rag.query.retrieval.traversal.loop.async_retry", AsyncMock(side_effect=responses)):
        result = await run_corpus_traversal("Câu hỏi", snapshot, max_turns=2)

    assert result.status == "no_match"
    assert result.termination_reason == "max_turns_reached_2"
    assert result.turn_count == 2
    assert result.file_candidates == []
    assert result.faq_candidates == []
