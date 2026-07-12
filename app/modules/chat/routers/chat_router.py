"""
Chat Endpoints - Handle all RAG-based chat operations.
Includes: query and stream.
"""

from __future__ import annotations

import json
import logging
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from google.genai.errors import APIError

from app.core.auth import JWTPayload
from app.core.dependencies import require_auth
from app.core.exceptions import AppException, handle_google_api_error
from app.modules.chat.dtos import (
    ChatMessageListResponse,
    ChatQueryRequest,
    ChatQueryResponse,
    ChatSessionListResponse,
    ChatSessionMutationResponse,
    ChatSessionRenameRequest,
    ChatStreamRequest,
)
from app.modules.chat.services.chat_conversation_service import (
    get_chat_query_conversation_service,
    get_chat_stream_conversation_service,
    user_context_from_jwt,
)
from app.modules.chat.services.chat_session_service import get_chat_session_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["Chat"])


def _sse_event(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _stream_api_error_payload(exc: APIError, session_id: str) -> dict:
    ai_code = getattr(exc, "code", 500)
    if not isinstance(ai_code, int) or ai_code < 400:
        ai_code = 500
    if ai_code == 429:
        return {
            "error": "rate_limit_exceeded",
            "message": "Quá tải hệ thống AI. Vui lòng thử lại sau.",
            "statusCode": 429,
            "done": True,
            "sessionId": session_id,
        }
    if ai_code == 500 and ("500 INTERNAL" in str(exc) or "Internal error encountered" in str(exc)):
        return {
            "error": "ai_service_error",
            "message": "Google internal server error",
            "statusCode": 500,
            "done": True,
            "sessionId": session_id,
        }
    return {
        "error": "ai_service_error",
        "message": str(exc),
        "statusCode": ai_code,
        "done": True,
        "sessionId": session_id,
    }


@router.post(
    "/query",
    response_model=ChatQueryResponse,
    summary="Generate RAG-based chat response",
    description="Process a user question with Corpus Tree RAG traversal and return a complete answer.",
)
async def chat_query(
    request: ChatQueryRequest,
    user: JWTPayload = Depends(require_auth),
):
    """Handle a single chat query with RAG support."""
    try:
        user_context = user_context_from_jwt(user)
        return await get_chat_query_conversation_service().query(request, user_context)
    except ValueError as exc:
        logger.error("[Chat] ValueError during chat_query: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except APIError as exc:
        ai_code = getattr(exc, "code", 500)
        if ai_code == 429:
            logger.warning("[Chat] Rate limit exceeded (429) for user %s", user.user_id)
        else:
            logger.error("[Chat] Gemini APIError (%s) for user %s: %s", ai_code, user.user_id, exc)
        raise handle_google_api_error(exc) from exc
    except AppException as exc:
        logger.error("[Chat] AppException during chat_query for user %s: %s", user.user_id, exc)
        raise
    except Exception as exc:
        logger.error(
            "[Chat] Unexpected error during chat_query for user %s: %s",
            user.user_id,
            exc,
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate chat response: {str(exc)}",
        ) from exc


@router.post(
    "/stream",
    summary="Stream RAG-based chat response",
    description="Stream chat response with RAG using Server-Sent Events (SSE).",
    response_class=StreamingResponse,
)
async def chat_stream(
    request: ChatStreamRequest,
    user: JWTPayload = Depends(require_auth),
):
    """Stream chat response in real-time using RAG."""
    user_context = user_context_from_jwt(user)
    session_id = request.session_id or str(uuid4())

    async def event_generator():
        try:
            async for event in get_chat_stream_conversation_service().stream_events(
                request,
                user_context,
                session_id=session_id,
            ):
                yield _sse_event(event)
        except ValueError as exc:
            logger.error("[Chat-Stream] ValueError during stream: %s", exc, exc_info=True)
            yield _sse_event({
                "error": str(exc),
                "done": True,
                "sessionId": session_id,
            })
        except APIError as exc:
            ai_code = getattr(exc, "code", 500)
            if ai_code == 429:
                logger.warning("[Chat-Stream] Rate limit exceeded (429) for user %s", user_context.user_id)
            else:
                logger.error("[Chat-Stream] Gemini APIError (%s): %s", ai_code, exc)
            yield _sse_event(_stream_api_error_payload(exc, session_id))
        except AppException as exc:
            logger.error("[Chat-Stream] AppException for user %s: %s", user_context.user_id, exc)
            yield _sse_event({
                "error": "app_error",
                "message": exc.message,
                "statusCode": exc.status_code,
                "done": True,
                "sessionId": session_id,
            })
        except Exception as exc:
            logger.error(
                "[Chat-Stream] Unexpected error for user %s: %s",
                user_context.user_id,
                exc,
                exc_info=True,
            )
            yield _sse_event({
                "error": "internal_error",
                "message": f"Failed to stream chat response: {str(exc)}",
                "done": True,
                "sessionId": session_id,
            })

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get(
    "/sessions",
    response_model=ChatSessionListResponse,
    summary="List chat sessions by current user",
)
async def list_chat_sessions(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100, alias="pageSize"),
    status_filter: str | None = Query(None, alias="statusFilter"),
    user: JWTPayload = Depends(require_auth),
):
    return await get_chat_session_service().list_sessions(
        user_id=user.user_id,
        page=page,
        page_size=page_size,
        status_filter=status_filter,
    )


@router.get(
    "/sessions/{session_id}/messages",
    response_model=ChatMessageListResponse,
    summary="List messages in a chat session",
)
async def list_chat_messages(
    session_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100, alias="pageSize"),
    user: JWTPayload = Depends(require_auth),
):
    return await get_chat_session_service().list_messages(
        session_id=session_id,
        user_id=user.user_id,
        page=page,
        page_size=page_size,
    )


@router.patch(
    "/sessions/{session_id}",
    response_model=ChatSessionMutationResponse,
    summary="Rename a chat session",
)
async def rename_chat_session(
    session_id: str,
    request: ChatSessionRenameRequest,
    user: JWTPayload = Depends(require_auth),
):
    return await get_chat_session_service().rename_session(
        session_id=session_id,
        user_id=user.user_id,
        title=request.title,
    )


@router.post(
    "/sessions/{session_id}/archive",
    response_model=ChatSessionMutationResponse,
    summary="Archive a chat session",
)
async def archive_chat_session(
    session_id: str,
    user: JWTPayload = Depends(require_auth),
):
    return await get_chat_session_service().archive_session(
        session_id=session_id,
        user_id=user.user_id,
    )


@router.post(
    "/sessions/{session_id}/unarchive",
    response_model=ChatSessionMutationResponse,
    summary="Unarchive a chat session",
)
async def unarchive_chat_session(
    session_id: str,
    user: JWTPayload = Depends(require_auth),
):
    return await get_chat_session_service().unarchive_session(
        session_id=session_id,
        user_id=user.user_id,
    )


@router.delete(
    "/sessions/{session_id}",
    response_model=ChatSessionMutationResponse,
    summary="Delete a chat session and its messages",
)
async def delete_chat_session(
    session_id: str,
    user: JWTPayload = Depends(require_auth),
):
    return await get_chat_session_service().delete_session(
        session_id=session_id,
        user_id=user.user_id,
    )
