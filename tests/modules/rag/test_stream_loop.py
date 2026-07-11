from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from google.genai import types

from app.modules.rag.query.answering.pageindex.stream_loop import stream_agent_loop


class _AsyncStream:
    def __init__(self, chunks):
        self._chunks = chunks

    def __aiter__(self):
        self._iter = iter(self._chunks)
        return self

    async def __anext__(self):
        try:
            return next(self._iter)
        except StopIteration:
            raise StopAsyncIteration


def _chunk(parts):
    return SimpleNamespace(
        candidates=[SimpleNamespace(content=types.Content(role="model", parts=parts))],
        usage_metadata=SimpleNamespace(prompt_token_count=1, candidates_token_count=1),
    )


@pytest.mark.asyncio
async def test_stream_agent_loop_emits_tool_text_and_final_result():
    async def tool(**_kwargs):
        return "{}"

    call_part = types.Part.from_function_call(
        name="get_document_structure",
        args={"file_id": "1", "reasoning": "Cần xem mục lục"},
    )
    text_part = types.Part.from_text(text="<answer>Câu trả lời</answer>")

    retry_mock = AsyncMock(side_effect=[
        _AsyncStream([_chunk([call_part])]),
        _AsyncStream([_chunk([text_part])]),
    ])

    with patch(
        "app.modules.rag.query.answering.pageindex.stream_loop.get_agent_config",
        return_value=([], {"get_document_structure": tool}, object()),
    ), patch(
        "app.modules.rag.query.answering.pageindex.stream_loop.async_retry",
        retry_mock,
    ), patch(
        "app.modules.rag.query.answering.pageindex.stream_loop.build_sources_from_steps",
        AsyncMock(return_value=[]),
    ):
        events = []
        async for event in stream_agent_loop(
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
