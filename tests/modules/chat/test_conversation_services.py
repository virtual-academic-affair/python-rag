import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.modules.chat.dtos import ChatQueryRequest, ChatStreamRequest, UserContext
from app.modules.chat.services.chat_conversation_service import (
    ChatQueryConversationService,
    ChatStreamConversationService,
)


class FakeHistoryRepo:
    def __init__(self, recent=None):
        self.recent = recent or []
        self.calls = []

    async def ensure_session(self, **kwargs):
        self.calls.append(("ensure_session", kwargs))

    async def get_recent_messages(self, **kwargs):
        self.calls.append(("get_recent_messages", kwargs))
        return self.recent

    async def append_message(self, **kwargs):
        self.calls.append(("append_message", kwargs))


@pytest.mark.asyncio
async def test_chat_query_conversation_persists_user_and_assistant():
    repo = FakeHistoryRepo([SimpleNamespace(role="user", content="old")])
    chat_service = SimpleNamespace(
        generate_chat_response=AsyncMock(return_value={
            "answer": "answer",
            "source": "llm",
            "sources": [],
            "steps": [{"type": "retrieval"}],
            "token_usage": None,
            "processing_time_ms": 12,
        })
    )
    svc = ChatQueryConversationService(history_repo=repo, chat_service=chat_service)

    response = await svc.query(
        ChatQueryRequest(question="q"),
        UserContext(user_id="u1", name="User", role="student"),
    )

    assert response.session_id
    assert response.answer == "answer"
    assert [call[0] for call in repo.calls] == [
        "ensure_session",
        "get_recent_messages",
        "append_message",
        "append_message",
    ]
    assert repo.calls[2][1]["role"] == "user"
    assert repo.calls[3][1]["role"] == "assistant"
    chat_service.generate_chat_response.assert_awaited_once()
    assert chat_service.generate_chat_response.await_args.kwargs["chat_history"][0].content == "old"


@pytest.mark.asyncio
async def test_chat_query_conversation_skips_empty_assistant_answer():
    repo = FakeHistoryRepo()
    chat_service = SimpleNamespace(
        generate_chat_response=AsyncMock(return_value={
            "answer": "   ",
            "sources": [],
            "steps": [],
            "token_usage": None,
            "processing_time_ms": 1,
        })
    )
    svc = ChatQueryConversationService(history_repo=repo, chat_service=chat_service)

    response = await svc.query(
        ChatQueryRequest(question="q", session_id="session-1"),
        UserContext(user_id="u1", name="User", role="student"),
    )

    assert response.session_id == "session-1"
    assert [call[1]["role"] for call in repo.calls if call[0] == "append_message"] == ["user"]


@pytest.mark.asyncio
async def test_chat_stream_conversation_yields_dicts_and_persists_final_text():
    repo = FakeHistoryRepo([SimpleNamespace(role="assistant", content="old answer")])

    async def stream_chat_response(**_kwargs):
        yield json.dumps({"type": "text", "content": "A", "done": False})
        yield json.dumps({"type": "text", "content": "B", "done": False})
        yield json.dumps({
            "done": True,
            "tokenUsage": {"promptTokens": 1, "completionTokens": 2, "totalTokens": 3},
            "sources": [],
            "steps": [],
            "processingTimeMs": 20,
        })

    stream_service = SimpleNamespace(stream_chat_response=stream_chat_response)
    svc = ChatStreamConversationService(history_repo=repo, stream_service=stream_service)

    events = [
        event
        async for event in svc.stream_events(
            ChatStreamRequest(question="q"),
            UserContext(user_id="u1", name="User", role="student"),
            session_id="session-1",
        )
    ]

    assert events[0]["sessionId"] == "session-1"
    assert all(isinstance(event, dict) for event in events)
    assistant_appends = [
        call[1]
        for call in repo.calls
        if call[0] == "append_message" and call[1]["role"] == "assistant"
    ]
    assert assistant_appends[0]["content"] == "AB"
    assert assistant_appends[0]["token_usage"] == {
        "promptTokens": 1,
        "completionTokens": 2,
        "totalTokens": 3,
    }


@pytest.mark.asyncio
async def test_chat_stream_conversation_falls_back_to_final_payload_answer():
    repo = FakeHistoryRepo()

    async def stream_chat_response(**_kwargs):
        yield json.dumps({"done": True, "answer": "final answer"})

    svc = ChatStreamConversationService(
        history_repo=repo,
        stream_service=SimpleNamespace(stream_chat_response=stream_chat_response),
    )

    events = [
        event
        async for event in svc.stream_events(
            ChatStreamRequest(question="q", session_id="session-1"),
            UserContext(user_id="u1", name="User", role="student"),
        )
    ]

    assert events[-1]["answer"] == "final answer"
    assistant_appends = [
        call[1]
        for call in repo.calls
        if call[0] == "append_message" and call[1]["role"] == "assistant"
    ]
    assert assistant_appends[0]["content"] == "final answer"


@pytest.mark.asyncio
async def test_chat_stream_conversation_propagates_stream_errors():
    repo = FakeHistoryRepo()

    async def stream_chat_response(**_kwargs):
        raise RuntimeError("stream down")
        yield

    svc = ChatStreamConversationService(
        history_repo=repo,
        stream_service=SimpleNamespace(stream_chat_response=stream_chat_response),
    )

    with pytest.raises(RuntimeError, match="stream down"):
        async for _event in svc.stream_events(
            ChatStreamRequest(question="q", session_id="session-1"),
            UserContext(user_id="u1", name="User", role="student"),
        ):
            pass
