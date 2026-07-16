"""Chat session management service."""

from __future__ import annotations

from typing import Optional

from app.core.exceptions import NotFoundException, ValidationException
from app.modules.chat.dtos import (
    ChatMessageItem,
    ChatMessageListResponse,
    ChatSessionItem,
    ChatSessionListResponse,
    ChatSessionMutationResponse,
)
from app.modules.chat.repositories.chat_history_repository import (
    ChatHistoryRepository,
    get_chat_history_repository,
)


def to_iso_str(value):
    if not value:
        return None
    if isinstance(value, str):
        return value
    try:
        return value.isoformat()
    except AttributeError:
        return str(value)


class ChatSessionService:
    """Owns chat session query/mutation workflows and DTO mapping."""

    def __init__(self, history_repo: ChatHistoryRepository | None = None):
        self._history_repo = history_repo or get_chat_history_repository()

    async def list_sessions(
        self,
        *,
        user_id: str,
        page: int = 1,
        page_size: int = 20,
        status_filter: Optional[str] = None,
    ) -> ChatSessionListResponse:
        page, page_size = self._normalize_pagination(page, page_size)
        skip = (page - 1) * page_size
        normalized_status = self._normalize_status_filter(status_filter)

        sessions, total = await self._history_repo.list_sessions_by_user(
            user_id=user_id,
            limit=page_size,
            skip=skip,
            status=normalized_status,
        )
        items = [
            ChatSessionItem(
                session_id=session.session_id,
                title=session.title,
                status=session.status,
                message_count=int(session.message_count or 0),
                last_message_at=to_iso_str(session.last_message_at),
                created_at=to_iso_str(session.created_at),
                updated_at=to_iso_str(session.updated_at),
            )
            for session in sessions
        ]
        return ChatSessionListResponse(
            page=page,
            page_size=page_size,
            total=total,
            items=items,
        )

    async def list_messages(
        self,
        *,
        session_id: str,
        user_id: str,
        page: int = 1,
        page_size: int = 20,
    ) -> ChatMessageListResponse:
        page, page_size = self._normalize_pagination(page, page_size)
        skip = (page - 1) * page_size
        messages, total = await self._history_repo.list_messages_by_session(
            session_id=session_id,
            user_id=user_id,
            limit=page_size,
            skip=skip,
        )
        items = [
            ChatMessageItem(
                role=message.role,
                content=message.content,
                sequence=int(message.sequence or 0),
                message_type=message.message_type,
                token_usage=message.token_usage,
                sources=message.sources,
                steps=message.steps or None,
                processing_time_ms=message.processing_time_ms,
                faq_recommendation=getattr(message, "faq_recommendation", None),
                created_at=to_iso_str(message.created_at),
            )
            for message in messages
        ]
        return ChatMessageListResponse(
            session_id=session_id,
            page=page,
            page_size=page_size,
            total=total,
            items=items,
        )

    async def rename_session(self, *, session_id: str, user_id: str, title: str) -> ChatSessionMutationResponse:
        updated = await self._history_repo.rename_session(
            session_id=session_id,
            user_id=user_id,
            title=title,
        )
        if not updated:
            raise NotFoundException("Session", session_id)
        return ChatSessionMutationResponse(session_id=session_id, success=True)

    async def archive_session(self, *, session_id: str, user_id: str) -> ChatSessionMutationResponse:
        updated = await self._history_repo.archive_session(session_id=session_id, user_id=user_id)
        if not updated:
            raise NotFoundException("Session", session_id)
        return ChatSessionMutationResponse(session_id=session_id, success=True)

    async def unarchive_session(self, *, session_id: str, user_id: str) -> ChatSessionMutationResponse:
        updated = await self._history_repo.unarchive_session(session_id=session_id, user_id=user_id)
        if not updated:
            raise NotFoundException("Session", session_id)
        return ChatSessionMutationResponse(session_id=session_id, success=True)

    async def delete_session(self, *, session_id: str, user_id: str) -> ChatSessionMutationResponse:
        deleted = await self._history_repo.delete_session(session_id=session_id, user_id=user_id)
        if not deleted:
            raise NotFoundException("Session", session_id)
        return ChatSessionMutationResponse(session_id=session_id, success=True)

    def _normalize_status_filter(self, status_filter: Optional[str]) -> str:
        normalized = (
            status_filter.strip().lower()
            if status_filter
            else self._history_repo.SESSION_STATUS_ACTIVE
        )
        valid_statuses = {
            self._history_repo.SESSION_STATUS_ACTIVE,
            self._history_repo.SESSION_STATUS_ARCHIVED,
        }
        if normalized not in valid_statuses:
            raise ValidationException("Invalid statusFilter. Allowed values: active, archived")
        return normalized

    @staticmethod
    def _normalize_pagination(page: int, page_size: int) -> tuple[int, int]:
        normalized_page = max(1, page)
        normalized_page_size = min(max(1, page_size), 100)
        return normalized_page, normalized_page_size


_chat_session_service: Optional[ChatSessionService] = None


def get_chat_session_service() -> ChatSessionService:
    global _chat_session_service
    if _chat_session_service is None:
        _chat_session_service = ChatSessionService()
    return _chat_session_service
