from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.integrations.llm.contracts import LLMResponse, LLMToolCall, LLMUsage
from app.modules.rag.query.answering.pageindex_agent.loop import run_pageindex_agent_loop


@pytest.mark.asyncio
async def test_pageindex_loop_preserves_tool_call_id_in_history():
    tool_call = LLMToolCall(
        id="call-1",
        name="get_document_structure",
        arguments={"file_id": "1", "reasoning": "Cần xem cấu trúc tài liệu."},
    )
    first_response = LLMResponse(
        text="",
        tool_calls=[tool_call],
        assistant_message={
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "id": "call-1",
                "type": "function",
                "function": {
                    "name": "get_document_structure",
                    "arguments": '{"file_id":"1","reasoning":"Cần xem cấu trúc tài liệu."}',
                },
            }],
        },
        usage=LLMUsage(2, 1, 3),
    )
    second_response = LLMResponse(
        text="<answer>Câu trả lời</answer>",
        tool_calls=[],
        assistant_message={"role": "assistant", "content": "<answer>Câu trả lời</answer>"},
        usage=LLMUsage(3, 2, 5),
    )
    gateway = SimpleNamespace(complete=AsyncMock(side_effect=[first_response, second_response]))
    tool = AsyncMock(return_value='{"nodes": []}')

    with patch(
        "app.modules.rag.query.answering.pageindex_agent.loop.get_agent_config",
        return_value=([], {"get_document_structure": tool}),
    ), patch(
        "app.modules.rag.query.answering.pageindex_agent.loop.get_llm_gateway",
        return_value=gateway,
    ), patch(
        "app.modules.rag.query.answering.pageindex_agent.loop.build_sources_from_steps",
        AsyncMock(return_value=[]),
    ):
        result = await run_pageindex_agent_loop(
            candidate_files=[{"file_id": "file-1", "file_name": "Quy chế"}],
            prompt_contents="Câu hỏi",
        )

    second_history = gateway.complete.await_args_list[1].kwargs["messages"]
    assistant_tool_message = next(message for message in second_history if message.get("tool_calls"))
    tool_message = next(message for message in second_history if message.get("role") == "tool")
    assert assistant_tool_message["tool_calls"][0]["id"] == "call-1"
    assert tool_message == {
        "role": "tool",
        "tool_call_id": "call-1",
        "name": "get_document_structure",
        "content": '{"nodes": []}',
    }
    assert result["final_answer"] == "Câu trả lời"
    assert result["tokenUsage"] == {
        "promptTokens": 5,
        "completionTokens": 3,
        "totalTokens": 8,
    }
