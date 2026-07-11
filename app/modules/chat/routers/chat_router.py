"""
Chat Endpoints - Handle all RAG-based chat operations.
Includes: query and stream.
"""

from fastapi import APIRouter, HTTPException, status, Depends, Query
from fastapi.responses import StreamingResponse
import json
from uuid import uuid4
from google.genai.errors import APIError
import logging

from app.modules.chat.dtos import (
    ChatQueryRequest,
    ChatQueryResponse,
    ChatStreamRequest,
    UserContext,
    ChatHistoryItem,
    ChatSessionListResponse,
    ChatSessionItem,
    ChatMessageListResponse,
    ChatMessageItem,
    ChatSessionRenameRequest,
    ChatSessionMutationResponse,
)
from app.core.dependencies import require_auth
from app.core.auth import JWTPayload
from app.modules.chat.services.chat_service import get_chat_service
from app.modules.chat.services.chat_stream_service import get_chat_stream_service
from app.modules.chat.repositories.chat_history_repository import get_chat_history_repository
from app.core.config import settings
from app.core.exceptions import AppException, NotFoundException, ValidationException, handle_google_api_error

logger = logging.getLogger(__name__)

def to_iso_str(val):
    if not val:
        return None
    if isinstance(val, str):
        return val
    try:
        return val.isoformat()
    except AttributeError:
        return str(val)

router = APIRouter(prefix="/chat", tags=["Chat"])


@router.post(
    "/query",
    response_model=ChatQueryResponse,
    summary="Generate RAG-based chat response",
    description="Process a user question with Corpus Tree RAG traversal and return a complete answer.",
)
async def chat_query(
    request: ChatQueryRequest,
    user: JWTPayload = Depends(require_auth)
):
    """
    Handle a single chat query with RAG support.
    """
    try:
        user_context = UserContext(
            user_id=user.user_id,
            name=user.display_name,
            enrollment_year=user.enrollment_year,
            role=user.role,
        )

        session_id = request.session_id or str(uuid4())

        chat_history_repo = get_chat_history_repository()
        await chat_history_repo.ensure_session(session_id=session_id, user_id=user_context.user_id)

        raw_history = await chat_history_repo.get_recent_messages(
            session_id=session_id,
            user_id=user_context.user_id,
            limit=6,
        )
        chat_history = [
            ChatHistoryItem(role=m.role, content=m.content)
            for m in raw_history
        ]

        await chat_history_repo.append_message(
            session_id=session_id,
            user_id=user_context.user_id,
            role="user",
            content=request.question,
        )

        chat_svc = get_chat_service()
        result = await chat_svc.generate_chat_response(
            question=request.question,
            user_context=user_context,
            chat_history=chat_history,
            resolve_citations=request.resolve_citations,
            citation_link_type=request.citation_link_type,
            to_rich_text=request.to_rich_text,
        )

        answer_content = result.get("answer", "")
        if answer_content.strip():
            await chat_history_repo.append_message(
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

    except ValueError as e:
        logger.error(f"[Chat] ValueError during chat_query: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except APIError as e:
        ai_code = getattr(e, "code", 500)
        if ai_code == 429:
            logger.warning(f"[Chat] Rate limit exceeded (429) for user {user.user_id}")
        else:
            logger.error(f"[Chat] Gemini APIError ({ai_code}) for user {user.user_id}: {e}")
        raise handle_google_api_error(e)
    except AppException as e:
        logger.error(f"[Chat] AppException during chat_query for user {user.user_id}: {e}")
        raise
    except Exception as e:
        logger.error(f"[Chat] Unexpected error during chat_query for user {user.user_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate chat response: {str(e)}",
        )


@router.post(
    "/stream",
    summary="Stream RAG-based chat response",
    description="Stream chat response with RAG using Server-Sent Events (SSE).",
    response_class=StreamingResponse,
)
async def chat_stream(
    request: ChatStreamRequest,
    user: JWTPayload = Depends(require_auth)
):
    """
    Stream chat response in real-time using RAG.
    """
    try:
        user_context = UserContext(
            user_id=user.user_id,
            name=user.display_name,
            enrollment_year=user.enrollment_year,
            role=user.role,
        )

        session_id = request.session_id or str(uuid4())
        chat_history_repo = get_chat_history_repository()
        await chat_history_repo.ensure_session(session_id=session_id, user_id=user_context.user_id)

        raw_history = await chat_history_repo.get_recent_messages(
            session_id=session_id,
            user_id=user_context.user_id,
            limit=6,
        )
        chat_history = [
            ChatHistoryItem(role=m.role, content=m.content)
            for m in raw_history
        ]

        await chat_history_repo.append_message(
            session_id=session_id,
            user_id=user_context.user_id,
            role="user",
            content=request.question,
        )

        async def event_generator():
            assistant_chunks: list[str] = []
            is_first_chunk = True
            try:
                chat_stream_svc = get_chat_stream_service()
                async for chunk_json in chat_stream_svc.stream_chat_response(
                    question=request.question,
                    user_context=user_context,
                    chat_history=chat_history,
                    resolve_citations=request.resolve_citations,
                    citation_link_type=request.citation_link_type,
                ):
                    payload = json.loads(chunk_json)
                    
                    if is_first_chunk:
                        payload["sessionId"] = session_id
                        is_first_chunk = False
                    
                    if payload.get("type") == "text" and payload.get("content"):
                        assistant_chunks.append(payload["content"])

                    if payload.get("done") is True:
                        assistant_content = "".join(assistant_chunks)
                        if not assistant_content:
                            assistant_content = (
                                payload.get("answer")
                                or payload.get("content")
                                or payload.get("final_answer")
                                or ""
                            )

                        if assistant_content.strip():
                            await chat_history_repo.append_message(
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
                    
                    chunk_json = json.dumps(payload, ensure_ascii=False)
                    yield f"data: {chunk_json}\n\n"
            except ValueError as e:
                logger.error(f"[Chat-Stream] ValueError during stream: {e}", exc_info=True)
                error_data = json.dumps({
                    "error": str(e),
                    "done": True,
                    "sessionId": session_id
                })
                yield f"data: {error_data}\n\n"
            except APIError as e:
                ai_code = getattr(e, "code", 500)
                if not isinstance(ai_code, int) or ai_code < 400:
                    ai_code = 500
                if ai_code == 429:
                    logger.warning(f"[Chat-Stream] Rate limit exceeded (429) for user {user_context.user_id}")
                    error_data = json.dumps({
                        "error": "rate_limit_exceeded",
                        "message": "Quá tải hệ thống AI. Vui lòng thử lại sau.",
                        "statusCode": 429,
                        "done": True,
                        "sessionId": session_id
                    })
                elif ai_code == 500 and ("500 INTERNAL" in str(e) or "Internal error encountered" in str(e)):
                    logger.error(f"[Chat-Stream] Google internal server error (500): {e}")
                    error_data = json.dumps({
                        "error": "ai_service_error",
                        "message": "Google internal server error",
                        "statusCode": 500,
                        "done": True,
                        "sessionId": session_id
                    })
                else:
                    logger.error(f"[Chat-Stream] Gemini APIError ({ai_code}): {e}")
                    error_data = json.dumps({
                        "error": "ai_service_error",
                        "message": str(e),
                        "statusCode": ai_code,
                        "done": True,
                        "sessionId": session_id
                    })
                yield f"data: {error_data}\n\n"
            except Exception as e:
                logger.error(f"[Chat-Stream] Unexpected error for user {user_context.user_id}: {e}", exc_info=True)
                error_data = json.dumps({
                    "error": "internal_error",
                    "message": f"Failed to stream chat response: {str(e)}",
                    "done": True,
                    "sessionId": session_id
                })
                yield f"data: {error_data}\n\n"

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except APIError as e:
        raise handle_google_api_error(e)
    except AppException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to stream chat response: {str(e)}",
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
    page = max(1, page)
    page_size = min(max(1, page_size), 100)
    skip = (page - 1) * page_size

    repo = get_chat_history_repository()
    user_id = user.user_id

    normalized_status_filter = (
        status_filter.strip().lower() if status_filter else repo.SESSION_STATUS_ACTIVE
    )
    valid_statuses = {
        repo.SESSION_STATUS_ACTIVE,
        repo.SESSION_STATUS_ARCHIVED,
    }
    if normalized_status_filter not in valid_statuses:
        raise ValidationException("Invalid statusFilter. Allowed values: active, archived")

    sessions, total = await repo.list_sessions_by_user(
        user_id=user_id,
        limit=page_size,
        skip=skip,
        status=normalized_status_filter,
    )

    items = [
        ChatSessionItem(
            session_id=s.session_id,
            title=s.title,
            status=s.status,
            message_count=int(s.message_count or 0),
            last_message_at=to_iso_str(s.last_message_at),
            created_at=to_iso_str(s.created_at),
            updated_at=to_iso_str(s.updated_at),
        )
        for s in sessions
    ]

    return ChatSessionListResponse(page=page, page_size=page_size, total=total, items=items)


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
    page = max(1, page)
    page_size = min(max(1, page_size), 100)
    skip = (page - 1) * page_size

    repo = get_chat_history_repository()
    user_id = user.user_id
    messages, total = await repo.list_messages_by_session(
        session_id=session_id,
        user_id=user_id,
        limit=page_size,
        skip=skip,
    )

    items = [
        ChatMessageItem(
            role=m.role,
            content=m.content,
            sequence=int(m.sequence or 0),
            message_type=m.message_type,
            token_usage=m.token_usage,
            sources=m.sources,
            steps=m.steps or None,
            processing_time_ms=m.processing_time_ms,
            created_at=to_iso_str(m.created_at),
        )
        for m in messages
    ]

    return ChatMessageListResponse(
        session_id=session_id,
        page=page,
        page_size=page_size,
        total=total,
        items=items,
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
    repo = get_chat_history_repository()
    user_id = user.user_id
    updated = await repo.rename_session(session_id=session_id, user_id=user_id, title=request.title)
    if not updated:
        raise NotFoundException("Session", session_id)
    return ChatSessionMutationResponse(session_id=session_id, success=True)


@router.post(
    "/sessions/{session_id}/archive",
    response_model=ChatSessionMutationResponse,
    summary="Archive a chat session",
)
async def archive_chat_session(
    session_id: str,
    user: JWTPayload = Depends(require_auth),
):
    repo = get_chat_history_repository()
    user_id = user.user_id
    updated = await repo.archive_session(session_id=session_id, user_id=user_id)
    if not updated:
        raise NotFoundException("Session", session_id)
    return ChatSessionMutationResponse(session_id=session_id, success=True)


@router.post(
    "/sessions/{session_id}/unarchive",
    response_model=ChatSessionMutationResponse,
    summary="Unarchive a chat session",
)
async def unarchive_chat_session(
    session_id: str,
    user: JWTPayload = Depends(require_auth),
):
    repo = get_chat_history_repository()
    user_id = user.user_id
    updated = await repo.unarchive_session(session_id=session_id, user_id=user_id)
    if not updated:
        raise NotFoundException("Session", session_id)
    return ChatSessionMutationResponse(session_id=session_id, success=True)


@router.delete(
    "/sessions/{session_id}",
    response_model=ChatSessionMutationResponse,
    summary="Delete a chat session and its messages",
)
async def delete_chat_session(
    session_id: str,
    user: JWTPayload = Depends(require_auth),
):
    repo = get_chat_history_repository()
    user_id = user.user_id
    deleted = await repo.delete_session(session_id=session_id, user_id=user_id)
    if not deleted:
        raise NotFoundException("Session", session_id)
    return ChatSessionMutationResponse(session_id=session_id, success=True)
