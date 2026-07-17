from unittest.mock import AsyncMock, patch

import pytest

from app.integrations.llm.contracts import LLMStreamChunk, LLMToolCallDelta, LLMUsage
from app.modules.rag.query.answering.pageindex_agent.stream_loop import stream_pageindex_agent_loop


class _Gateway:
    def __init__(self, streams):
        self._streams = iter(streams)

    async def stream(self, **_kwargs):
        for chunk in next(self._streams):
            yield chunk


@pytest.mark.asyncio
async def test_stream_pageindex_agent_loop_emits_tool_text_and_final_result():
    async def tool(**_kwargs):
        return "{}"

    gateway = _Gateway([
        [
            LLMStreamChunk(
                tool_call_deltas=[LLMToolCallDelta(
                    index=0,
                    id="call-1",
                    name="get_document_structure",
                    arguments_delta='{"file_id":"1","reasoning":"Cần xem mục lục"}',
                )],
            ),
            LLMStreamChunk(usage=LLMUsage(1, 1, 2), finish_reason="tool_calls"),
        ],
        [
            LLMStreamChunk(text_delta="<answer>Câu trả lời</answer>"),
            LLMStreamChunk(usage=LLMUsage(1, 1, 2), finish_reason="stop"),
        ],
    ])

    with patch(
        "app.modules.rag.query.answering.pageindex_agent.stream_loop.get_agent_config",
        return_value=([], {"get_document_structure": tool}),
    ), patch(
        "app.modules.rag.query.answering.pageindex_agent.stream_loop.get_llm_gateway",
        return_value=gateway,
    ), patch(
        "app.modules.rag.query.answering.pageindex_agent.stream_loop.build_sources_from_steps",
        AsyncMock(return_value=[]),
    ):
        events = []
        async for event in stream_pageindex_agent_loop(
            candidate_files=[{"file_id": "file-1", "file_name": "Quy chế", "doc_description": ""}],
            prompt_contents=[],
        ):
            events.append(event)

    assert events[0]["type"] == "reasoning"
    assert events[1]["type"] == "call"
    assert events[1]["step"]["args"] == {"file_id": "1"}
    assert any(event.get("type") == "text" and "Câu trả lời" in event.get("content", "") for event in events)
    final = events[-1]
    assert final["type"] == "_agent_result"
    assert final["final_answer"] == "Câu trả lời"
    assert final["token_usage"] == {"prompt_tokens": 2, "completion_tokens": 2, "total_tokens": 4}
