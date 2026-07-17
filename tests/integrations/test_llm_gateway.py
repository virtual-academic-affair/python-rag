import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.integrations.llm.contracts import LLMStreamAccumulator, LLMTool
from app.integrations.llm.gateway import LLMGateway, close_llm_clients


def _response(*, content="", tool_calls=None, usage=None):
    return SimpleNamespace(
        choices=[SimpleNamespace(
            finish_reason="stop",
            message=SimpleNamespace(content=content, tool_calls=tool_calls or []),
        )],
        usage=usage,
    )


@pytest.mark.asyncio
async def test_complete_normalizes_text_usage_and_request_config(monkeypatch):
    monkeypatch.setattr("app.integrations.llm.gateway.settings.LLM_API_KEY", "test-provider-key")
    completion = AsyncMock(return_value=_response(
        content="Xin chào",
        usage=SimpleNamespace(prompt_tokens=3, completion_tokens=2, total_tokens=5),
    ))
    gateway = LLMGateway(completion_fn=completion)

    result = await gateway.complete(
        messages=[{"role": "user", "content": "Chào"}],
        model="gemini/gemini-2.5-flash",
        temperature=0.0,
    )

    assert result.text == "Xin chào"
    assert result.usage.as_dict() == {
        "prompt_tokens": 3,
        "completion_tokens": 2,
        "total_tokens": 5,
    }
    kwargs = completion.await_args.kwargs
    assert kwargs["model"].startswith("gemini/")
    assert kwargs["api_key"] == "test-provider-key"
    assert kwargs["temperature"] == 0.0
    assert kwargs["num_retries"] == 0
    assert kwargs["stream"] is False


@pytest.mark.asyncio
async def test_complete_normalizes_tool_calls_and_schemas():
    async def handler(**_kwargs):
        return {}

    raw_call = SimpleNamespace(
        id="call-1",
        function=SimpleNamespace(name="inspect_topic", arguments='{"node_key":"root"}'),
    )
    completion = AsyncMock(return_value=_response(tool_calls=[raw_call]))
    gateway = LLMGateway(completion_fn=completion)
    tool = LLMTool(
        name="inspect_topic",
        description="Inspect a topic",
        parameters={
            "type": "object",
            "properties": {"node_key": {"type": "string"}},
            "required": ["node_key"],
        },
        handler=handler,
    )

    result = await gateway.complete(
        messages=[{"role": "user", "content": "Inspect"}],
        tools=[tool],
    )

    assert result.tool_calls[0].id == "call-1"
    assert result.tool_calls[0].name == "inspect_topic"
    assert result.tool_calls[0].arguments == {"node_key": "root"}
    assert result.assistant_message["tool_calls"][0]["function"]["arguments"] == '{"node_key":"root"}'
    assert completion.await_args.kwargs["tools"] == [tool.as_schema()]


class _AsyncStream:
    def __init__(self, chunks):
        self._chunks = chunks
        self.closed = False

    def __aiter__(self):
        self._iterator = iter(self._chunks)
        return self

    async def __anext__(self):
        try:
            return next(self._iterator)
        except StopIteration:
            raise StopAsyncIteration

    async def aclose(self):
        self.closed = True


def _chunk(*, content="", tool_calls=None, usage=None, finish_reason=None):
    choices = []
    if content or tool_calls or finish_reason:
        choices = [SimpleNamespace(
            delta=SimpleNamespace(content=content, tool_calls=tool_calls or []),
            finish_reason=finish_reason,
        )]
    return SimpleNamespace(choices=choices, usage=usage)


@pytest.mark.asyncio
async def test_stream_accumulates_fragmented_tool_arguments_and_usage():
    deltas = [
        SimpleNamespace(
            index=0,
            id="call-1",
            function=SimpleNamespace(name="get_page_content", arguments='{"file_id":"1",'),
        ),
        SimpleNamespace(
            index=0,
            id=None,
            function=SimpleNamespace(name=None, arguments='"pages":"1-2"}'),
        ),
    ]
    raw_stream = _AsyncStream([
        _chunk(tool_calls=[deltas[0]]),
        _chunk(tool_calls=[deltas[1]], finish_reason="tool_calls"),
        _chunk(usage=SimpleNamespace(prompt_tokens=7, completion_tokens=3, total_tokens=10)),
    ])
    completion = AsyncMock(return_value=raw_stream)
    gateway = LLMGateway(completion_fn=completion)
    accumulator = LLMStreamAccumulator()

    async for chunk in gateway.stream(messages=[{"role": "user", "content": "Read"}]):
        accumulator.add(chunk)

    result = accumulator.response()
    assert result.tool_calls[0].arguments == {"file_id": "1", "pages": "1-2"}
    assert json.loads(result.assistant_message["tool_calls"][0]["function"]["arguments"]) == {
        "file_id": "1",
        "pages": "1-2",
    }
    assert result.usage.as_dict() == {
        "prompt_tokens": 7,
        "completion_tokens": 3,
        "total_tokens": 10,
    }
    assert raw_stream.closed is True


@pytest.mark.asyncio
async def test_stream_closes_provider_stream_when_consumer_is_cancelled():
    waiting = asyncio.Event()

    class BlockingStream:
        def __init__(self):
            self.closed = False

        def __aiter__(self):
            return self

        async def __anext__(self):
            waiting.set()
            await asyncio.Event().wait()

        async def aclose(self):
            self.closed = True

    raw_stream = BlockingStream()
    gateway = LLMGateway(completion_fn=AsyncMock(return_value=raw_stream))
    stream = gateway.stream(messages=[{"role": "user", "content": "Read"}])
    next_chunk = asyncio.create_task(anext(stream))
    await waiting.wait()

    next_chunk.cancel()
    with pytest.raises(asyncio.CancelledError):
        await next_chunk

    assert raw_stream.closed is True


@pytest.mark.asyncio
async def test_close_llm_clients_delegates_to_litellm_cleanup(monkeypatch):
    cleanup = AsyncMock()
    monkeypatch.setattr("app.integrations.llm.gateway.litellm.close_litellm_async_clients", cleanup)

    await close_llm_clients()

    cleanup.assert_awaited_once_with()
