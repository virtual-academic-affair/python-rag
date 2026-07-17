from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import CorpusTraversalError
from app.integrations.llm.contracts import LLMResponse, LLMToolCall
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
    call = LLMToolCall(id=f"call-{name}", name=name, arguments=args)
    return LLMResponse(
        text="",
        tool_calls=[call],
        assistant_message={
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "id": call.id,
                "type": "function",
                "function": {"name": name, "arguments": "{}"},
            }],
        },
    )


def _gateway_patch(responses):
    complete = AsyncMock(side_effect=responses if isinstance(responses, list) else None)
    if not isinstance(responses, list):
        complete.return_value = responses
    return patch(
        "app.modules.rag.query.retrieval.traversal.loop.get_llm_gateway",
        return_value=SimpleNamespace(complete=complete),
    )


@pytest.mark.asyncio
async def test_run_corpus_traversal_requires_explicit_valid_selection():
    valid = _make_node("valid-topic", file_ids=["file-ok"])
    snapshot = build_filtered_snapshot_from_nodes([valid], {"file-ok"}, set())
    responses = [
        _tool_call_response("select_topics", {"selections": [{"node_key": "valid-topic", "scope": "subtree"}]}),
    ]
    with _gateway_patch(responses):
        result = await run_corpus_traversal("Câu hỏi", snapshot)

    assert result.status == "selected"
    assert [candidate.file_id for candidate in result.file_candidates] == ["file-ok"]
    assert result.turn_count == 1
    assert [step["action"] for step in result.steps] == ["select"]
    assert result.steps[0]["node_keys"] == ["valid-topic"]


@pytest.mark.asyncio
async def test_run_corpus_traversal_omits_invalid_tool_attempt_from_public_steps():
    valid = _make_node("valid-topic", file_ids=["file-ok"])
    snapshot = build_filtered_snapshot_from_nodes([valid], {"file-ok"}, set())
    responses = [
        _tool_call_response("expand_topic", {"node_key": "not-revealed"}),
        _tool_call_response("select_topics", {"selections": [{"node_key": "valid-topic", "scope": "subtree"}]}),
    ]
    with _gateway_patch(responses):
        result = await run_corpus_traversal("Câu hỏi", snapshot)

    assert result.status == "selected"
    assert [step["action"] for step in result.steps] == ["select"]


@pytest.mark.asyncio
async def test_run_corpus_traversal_retries_tool_call_with_missing_required_arguments():
    valid = _make_node("valid-topic", file_ids=["file-ok"])
    snapshot = build_filtered_snapshot_from_nodes([valid], {"file-ok"}, set())
    responses = [
        _tool_call_response("select_topics", {}),
        _tool_call_response("select_topics", {
            "selections": [{"node_key": "valid-topic", "scope": "subtree"}],
            "reasoning": "Chủ đề này phù hợp với câu hỏi.",
        }),
    ]
    gateway = SimpleNamespace(complete=AsyncMock(side_effect=responses))

    with patch(
        "app.modules.rag.query.retrieval.traversal.loop.get_llm_gateway",
        return_value=gateway,
    ):
        result = await run_corpus_traversal(
            "Câu hỏi",
            snapshot,
            include_reasoning=True,
        )

    assert result.status == "selected"
    assert result.turn_count == 2
    assert [step["type"] for step in result.steps] == ["reasoning", "corpus_traversal"]
    retry_history = gateway.complete.await_args_list[1].kwargs["messages"]
    invalid_result = next(
        message
        for message in retry_history
        if message.get("role") == "tool" and "missing required arguments" in message.get("content", "")
    )
    assert "missing required arguments: selections, reasoning" in invalid_result["content"]


@pytest.mark.asyncio
async def test_run_corpus_traversal_records_explicit_no_match_step():
    valid = _make_node("valid-topic", file_ids=["file-ok"])
    snapshot = build_filtered_snapshot_from_nodes([valid], {"file-ok"}, set())
    responses = [
        _tool_call_response("select_no_match", {"reason": "Không phù hợp"}),
    ]
    with _gateway_patch(responses):
        result = await run_corpus_traversal("Câu hỏi", snapshot)

    assert result.status == "no_match"
    assert result.turn_count == 1
    assert [step["action"] for step in result.steps] == ["no_match"]


@pytest.mark.asyncio
async def test_run_corpus_traversal_returns_no_match_at_max_turns():
    valid = _make_node("valid-topic", file_ids=["file-ok"])
    snapshot = build_filtered_snapshot_from_nodes([valid], {"file-ok"}, set())
    response = _tool_call_response("expand_topic", {"node_key": "valid-topic"})

    with _gateway_patch(response):
        result = await run_corpus_traversal("Câu hỏi", snapshot, max_turns=1)

    assert result.status == "no_match"
    assert result.termination_reason == "max_turns"
    assert result.turn_count == 1
    assert result.file_candidates == []
    assert result.faq_candidates == []
    assert result.expanded_node_keys == ["valid-topic"]
    assert [step["action"] for step in result.steps] == ["expand"]
    assert result.token_usage == {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
    }


@pytest.mark.asyncio
async def test_run_corpus_traversal_emits_reasoning_only_for_valid_tool_calls():
    valid = _make_node("valid-topic", file_ids=["file-ok"])
    snapshot = build_filtered_snapshot_from_nodes([valid], {"file-ok"}, set())
    responses = [
        _tool_call_response("expand_topic", {
            "node_key": "not-revealed",
            "reasoning": "Không được phát ra",
        }),
        _tool_call_response("select_topics", {
            "selections": [{"node_key": "valid-topic", "scope": "subtree"}],
            "reasoning": "Chủ đề này phù hợp trực tiếp với câu hỏi.",
        }),
    ]
    emitted = []

    async def on_step(step):
        emitted.append(step)

    with _gateway_patch(responses):
        result = await run_corpus_traversal(
            "Câu hỏi",
            snapshot,
            include_reasoning=True,
            on_step=on_step,
        )

    assert [step["type"] for step in emitted] == ["reasoning", "corpus_traversal"]
    assert emitted[0] == {
        "type": "reasoning",
        "content": "Chủ đề này phù hợp trực tiếp với câu hỏi.",
    }
    assert result.steps == emitted


@pytest.mark.asyncio
async def test_run_corpus_traversal_llm_failure_raises_unavailable():
    snapshot = build_filtered_snapshot_from_nodes([], {"file-ok"}, set())
    complete = AsyncMock(side_effect=RuntimeError("gemini down"))
    with patch(
        "app.modules.rag.query.retrieval.traversal.loop.get_llm_gateway",
        return_value=SimpleNamespace(complete=complete),
    ):
        with pytest.raises(CorpusTraversalError) as exc:
            await run_corpus_traversal("Câu hỏi", snapshot)
    assert exc.value.status_code == 502
    assert "tạm thời gặp sự cố" in exc.value.message


@pytest.mark.asyncio
async def test_run_corpus_traversal_no_tool_call_raises_unavailable():
    snapshot = build_filtered_snapshot_from_nodes([], {"file-ok"}, set())
    response = LLMResponse(
        text="done",
        tool_calls=[],
        assistant_message={"role": "assistant", "content": "done"},
    )
    with _gateway_patch(response):
        with pytest.raises(CorpusTraversalError, match="without explicit selection") as exc:
            await run_corpus_traversal("Câu hỏi", snapshot)
    assert exc.value.status_code == 502
    assert "tạm thời gặp sự cố" in exc.value.message
