import json

import pytest
from google.genai.errors import APIError

from app.core.auth import JWTPayload
from app.modules.chat.dtos import ChatQueryRequest, ChatQueryResponse, ChatStreamRequest
from app.modules.chat.routers import chat_router


async def _collect_sse(response):
    chunks = []
    async for chunk in response.body_iterator:
        if isinstance(chunk, bytes):
            chunk = chunk.decode("utf-8")
        chunks.append(chunk)
    return chunks


def _decode_sse(chunk: str) -> dict:
    assert chunk.startswith("data: ")
    assert chunk.endswith("\n\n")
    return json.loads(chunk[len("data: "):])


@pytest.mark.asyncio
async def test_chat_query_router_delegates_to_conversation_service(monkeypatch):
    calls = []

    class FakeQueryConversationService:
        async def query(self, request, user_context):
            calls.append((request, user_context))
            return ChatQueryResponse(
                session_id="s1",
                answer="answer",
                sources=[],
                steps=[],
                token_usage=None,
                processing_time_ms=1,
            )

    monkeypatch.setattr(
        chat_router,
        "get_chat_query_conversation_service",
        lambda: FakeQueryConversationService(),
    )

    response = await chat_router.chat_query(
        ChatQueryRequest(question="q"),
        JWTPayload(sub="u1", email="user@example.test"),
    )

    assert response.session_id == "s1"
    assert calls[0][0].question == "q"
    assert calls[0][1].user_id == "u1"


@pytest.mark.asyncio
async def test_chat_stream_router_encodes_event_dicts_as_sse(monkeypatch):
    class FakeStreamConversationService:
        async def stream_events(self, *_args, **_kwargs):
            yield {"type": "text", "content": "hello", "done": False, "sessionId": "s1"}
            yield {"done": True, "sessionId": "s1"}

    monkeypatch.setattr(
        chat_router,
        "get_chat_stream_conversation_service",
        lambda: FakeStreamConversationService(),
    )

    response = await chat_router.chat_stream(
        ChatStreamRequest(question="q", session_id="s1"),
        JWTPayload(sub="u1", email="user@example.test"),
    )
    chunks = await _collect_sse(response)

    assert _decode_sse(chunks[0]) == {
        "type": "text",
        "content": "hello",
        "done": False,
        "sessionId": "s1",
    }
    assert _decode_sse(chunks[1]) == {"done": True, "sessionId": "s1"}


@pytest.mark.asyncio
async def test_chat_stream_router_formats_rate_limit_error_event(monkeypatch):
    class FakeStreamConversationService:
        async def stream_events(self, *_args, **_kwargs):
            raise APIError(429, {"error": {"message": "rate"}})
            yield

    monkeypatch.setattr(
        chat_router,
        "get_chat_stream_conversation_service",
        lambda: FakeStreamConversationService(),
    )

    response = await chat_router.chat_stream(
        ChatStreamRequest(question="q", session_id="s1"),
        JWTPayload(sub="u1", email="user@example.test"),
    )
    chunks = await _collect_sse(response)

    assert _decode_sse(chunks[0]) == {
        "error": "rate_limit_exceeded",
        "message": "Quá tải hệ thống AI. Vui lòng thử lại sau.",
        "statusCode": 429,
        "done": True,
        "sessionId": "s1",
    }


@pytest.mark.asyncio
async def test_chat_stream_router_formats_generic_error_event(monkeypatch):
    class FakeStreamConversationService:
        async def stream_events(self, *_args, **_kwargs):
            raise RuntimeError("boom")
            yield

    monkeypatch.setattr(
        chat_router,
        "get_chat_stream_conversation_service",
        lambda: FakeStreamConversationService(),
    )

    response = await chat_router.chat_stream(
        ChatStreamRequest(question="q", session_id="s1"),
        JWTPayload(sub="u1", email="user@example.test"),
    )
    chunks = await _collect_sse(response)

    assert _decode_sse(chunks[0]) == {
        "error": "internal_error",
        "message": "Failed to stream chat response: boom",
        "done": True,
        "sessionId": "s1",
    }
