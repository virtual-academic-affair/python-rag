"""Chat conversation orchestration services.

These services own session/history persistence around chat query and stream
flows. They do not own HTTP/SSE wire formatting.
"""

from __future__ import annotations

import json
from typing import Any, AsyncGenerator, Optional
from uuid import uuid4

from app.core.auth import JWTPayload
from app.modules.chat.dtos import (
    ChatHistoryItem,
    ChatQueryRequest,
    ChatQueryResponse,
    ChatStreamRequest,
    UserContext,
)
from app.modules.chat.repositories.chat_history_repository import (
    ChatHistoryRepository,
    get_chat_history_repository,
)
from app.modules.chat.services.chat_service import ChatService, get_chat_service
from app.modules.chat.services.chat_stream_service import (
    ChatStreamService,
    get_chat_stream_service,
)


def user_context_from_jwt(user: JWTPayload) -> UserContext:
    return UserContext(
        user_id=user.user_id,
        name=user.display_name,
        enrollment_year=user.enrollment_year,
        role=user.role,
    )


async def _prepare_user_turn(
    history_repo: ChatHistoryRepository,
    *,
    session_id: str,
    user_context: UserContext,
    question: str,
) -> list[ChatHistoryItem]:
    await history_repo.ensure_session(
        session_id=session_id,
        user_id=user_context.user_id,
    )
    raw_history = await history_repo.get_recent_messages(
        session_id=session_id,
        user_id=user_context.user_id,
        limit=6,
    )
    chat_history = [
        ChatHistoryItem(role=message.role, content=message.content)
        for message in raw_history
    ]
    await history_repo.append_message(
        session_id=session_id,
        user_id=user_context.user_id,
        role="user",
        content=question,
    )
    return chat_history


class ChatQueryConversationService:
    """Orchestrates non-stream chat session persistence around ChatService."""

    def __init__(
        self,
        history_repo: ChatHistoryRepository | None = None,
        chat_service: ChatService | None = None,
    ):
        self._history_repo = history_repo or get_chat_history_repository()
        self._chat_service = chat_service or get_chat_service()

    async def query(
        self,
        request: ChatQueryRequest,
        user_context: UserContext,
    ) -> ChatQueryResponse:
        session_id = request.session_id or str(uuid4())
        chat_history = await _prepare_user_turn(
            self._history_repo,
            session_id=session_id,
            user_context=user_context,
            question=request.question,
        )

        result = await self._chat_service.generate_chat_response(
            question=request.question,
            user_context=user_context,
            chat_history=chat_history,
            resolve_citations=request.resolve_citations,
            citation_link_type=request.citation_link_type,
            to_rich_text=request.to_rich_text,
        )

        answer_content = result.get("answer", "")
        if answer_content.strip():
            await self._history_repo.append_message(
                session_id=session_id,
                user_id=user_context.user_id,
                role="assistant",
                content=answer_content,
                token_usage=result.get("token_usage"),
                sources=result.get("sources"),
                steps=result.get("steps"),
                processing_time_ms=result.get("processing_time_ms"),
            )

        return ChatQueryResponse(session_id=session_id, **result)


class ChatStreamConversationService:
    """Orchestrates streaming chat session persistence around ChatStreamService."""

    def __init__(
        self,
        history_repo: ChatHistoryRepository | None = None,
        stream_service: ChatStreamService | None = None,
    ):
        self._history_repo = history_repo or get_chat_history_repository()
        self._stream_service = stream_service or get_chat_stream_service()

    async def stream_events(
        self,
        request: ChatStreamRequest,
        user_context: UserContext,
        *,
        session_id: str | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        resolved_session_id = session_id or request.session_id or str(uuid4())
        chat_history = await _prepare_user_turn(
            self._history_repo,
            session_id=resolved_session_id,
            user_context=user_context,
            question=request.question,
        )

        assistant_chunks: list[str] = []
        is_first_chunk = True
        async for chunk_json in self._stream_service.stream_chat_response(
            question=request.question,
            user_context=user_context,
            chat_history=chat_history,
            resolve_citations=request.resolve_citations,
            citation_link_type=request.citation_link_type,
        ):
            payload = json.loads(chunk_json)

            if is_first_chunk:
                payload["sessionId"] = resolved_session_id
                is_first_chunk = False

            if payload.get("type") == "text" and payload.get("content"):
                assistant_chunks.append(payload["content"])

            if payload.get("done") is True:
                await self._persist_stream_final_answer(
                    session_id=resolved_session_id,
                    user_context=user_context,
                    assistant_chunks=assistant_chunks,
                    payload=payload,
                )

            yield payload

    async def _persist_stream_final_answer(
        self,
        *,
        session_id: str,
        user_context: UserContext,
        assistant_chunks: list[str],
        payload: dict[str, Any],
    ) -> None:
        assistant_content = "".join(assistant_chunks)
        if not assistant_content:
            assistant_content = (
                payload.get("answer")
                or payload.get("content")
                or payload.get("final_answer")
                or ""
            )

        if not assistant_content.strip():
            return

        await self._history_repo.append_message(
            session_id=session_id,
            user_id=user_context.user_id,
            role="assistant",
            content=assistant_content,
            token_usage=payload.get("token_usage") or payload.get("tokenUsage"),
            sources=payload.get("sources"),
            steps=payload.get("steps"),
            processing_time_ms=payload.get("processing_time_ms") or payload.get("processingTimeMs"),
            message_type="text",
        )


_chat_query_conversation_service: Optional[ChatQueryConversationService] = None
_chat_stream_conversation_service: Optional[ChatStreamConversationService] = None


def get_chat_query_conversation_service() -> ChatQueryConversationService:
    global _chat_query_conversation_service
    if _chat_query_conversation_service is None:
        _chat_query_conversation_service = ChatQueryConversationService()
    return _chat_query_conversation_service


def get_chat_stream_conversation_service() -> ChatStreamConversationService:
    global _chat_stream_conversation_service
    if _chat_stream_conversation_service is None:
        _chat_stream_conversation_service = ChatStreamConversationService()
    return _chat_stream_conversation_service
