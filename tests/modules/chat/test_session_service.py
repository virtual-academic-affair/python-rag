from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core.exceptions import NotFoundException, ValidationException
from app.modules.chat.services.chat_session_service import ChatSessionService


class FakeSessionRepo:
    SESSION_STATUS_ACTIVE = "active"
    SESSION_STATUS_ARCHIVED = "archived"

    def __init__(self):
        self.list_sessions_by_user = AsyncMock()
        self.list_messages_by_session = AsyncMock()
        self.rename_session = AsyncMock()
        self.archive_session = AsyncMock()
        self.unarchive_session = AsyncMock()
        self.delete_session = AsyncMock()


@pytest.mark.asyncio
async def test_chat_session_service_lists_sessions_with_normalized_status_and_pagination():
    repo = FakeSessionRepo()
    session = SimpleNamespace(
        session_id="s1",
        title="Title",
        status="active",
        message_count=2,
        last_message_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        created_at="created",
        updated_at=None,
    )
    repo.list_sessions_by_user.return_value = ([session], 1)
    svc = ChatSessionService(history_repo=repo)

    response = await svc.list_sessions(
        user_id="u1",
        page=0,
        page_size=200,
        status_filter=" ARCHIVED ",
    )

    repo.list_sessions_by_user.assert_awaited_once_with(
        user_id="u1",
        limit=100,
        skip=0,
        status="archived",
    )
    assert response.page == 1
    assert response.page_size == 100
    assert response.items[0].session_id == "s1"
    assert response.items[0].last_message_at == "2026-01-01T00:00:00+00:00"


@pytest.mark.asyncio
async def test_chat_session_service_rejects_invalid_status_filter():
    svc = ChatSessionService(history_repo=FakeSessionRepo())

    with pytest.raises(ValidationException, match="Invalid statusFilter"):
        await svc.list_sessions(user_id="u1", status_filter="deleted")


@pytest.mark.asyncio
async def test_chat_session_service_lists_messages():
    repo = FakeSessionRepo()
    message = SimpleNamespace(
        role="assistant",
        content="answer",
        sequence=2,
        message_type="text",
        token_usage=None,
        sources=[],
        steps=[],
        processing_time_ms=10,
        faq_recommendation={
            "effectiveQuestion": "answer question",
            "metadata": {
                "enrollmentYear": {"fromYear": 0, "toYear": 9999},
                "academicYear": {"fromYear": 0, "toYear": 9999},
            },
            "lecturerOnly": True,
        },
        created_at="created",
    )
    repo.list_messages_by_session.return_value = ([message], 1)
    svc = ChatSessionService(history_repo=repo)

    response = await svc.list_messages(
        session_id="s1",
        user_id="u1",
        page=2,
        page_size=10,
    )

    repo.list_messages_by_session.assert_awaited_once_with(
        session_id="s1",
        user_id="u1",
        limit=10,
        skip=10,
    )
    assert response.session_id == "s1"
    assert response.items[0].content == "answer"
    assert response.items[0].faq_recommendation.lecturer_only is True


@pytest.mark.asyncio
async def test_chat_session_service_treats_legacy_message_without_recommendation_as_none():
    repo = FakeSessionRepo()
    message = SimpleNamespace(
        role="assistant",
        content="legacy answer",
        sequence=2,
        message_type="text",
        token_usage=None,
        sources=[],
        steps=[],
        processing_time_ms=10,
        created_at="created",
    )
    repo.list_messages_by_session.return_value = ([message], 1)

    response = await ChatSessionService(history_repo=repo).list_messages(
        session_id="s1",
        user_id="u1",
    )

    assert response.items[0].faq_recommendation is None


@pytest.mark.asyncio
async def test_chat_session_service_mutation_raises_not_found_when_repo_returns_false():
    repo = FakeSessionRepo()
    repo.rename_session.return_value = False
    svc = ChatSessionService(history_repo=repo)

    with pytest.raises(NotFoundException):
        await svc.rename_session(session_id="missing", user_id="u1", title="New")
