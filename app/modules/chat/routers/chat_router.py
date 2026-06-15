"""
Chat Endpoints - Handle all RAG-based chat operations.
Includes: query, stream, and retrieval preview (Qdrant).
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
    ChatRetrievePreviewRequest,
    ChatRetrievePreviewResponse,
    ChatRetrievePreviewItem,
    ChatSessionListResponse,
    ChatSessionItem,
    ChatMessageListResponse,
    ChatMessageItem,
    ChatSessionRenameRequest,
    ChatSessionMutationResponse,
)
from app.core.dependencies import require_auth
from app.modules.chat.services.chat_service import get_chat_service
from app.modules.chat.services.chat_stream_service import get_chat_stream_service
from app.modules.chat.repositories.chat_history_repository import get_chat_history_repository
from app.modules.rag.retrieval.retrieval_service import get_retrieval_service
from app.core.config import settings
from app.core.exceptions import handle_google_api_error

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
    description="Process a user question with Qdrant RAG retrieval and return a complete answer.",
)
async def chat_query(
    request: ChatQueryRequest,
    user: dict = Depends(require_auth)
):
    """
    Handle a single chat query with RAG support.
    """
    try:
        user_context = UserContext(
            user_id=str(user.get("sub", "")),
            name=user.get("email", "").split("@")[0] if user.get("email") else "Unknown",
            enrollment_year=user.get("enrollment_year"),
            role=user.get("role", "student"),
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
            ChatHistoryItem(role=m["role"], content=m["content"])
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

        await chat_history_repo.append_message(
            session_id=session_id,
            user_id=user_context.user_id,
            role="assistant",
            content=result.get("answer", ""),
            token_usage=result.get("token_usage"),
            sources=result.get("sources"),
            steps=result.get("steps"),
            processing_time_ms=result.get("processing_time_ms"),
        )

        return ChatQueryResponse(session_id=session_id, **result)

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except APIError as e:
        raise handle_google_api_error(e)
    except Exception as e:
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
    user: dict = Depends(require_auth)
):
    """
    Stream chat response in real-time using RAG.
    """
    try:
        user_context = UserContext(
            user_id=str(user.get("sub", "")),
            name=user.get("email", "").split("@")[0] if user.get("email") else "Unknown",
            enrollment_year=user.get("enrollment_year"),
            role=user.get("role", "student"),
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
            ChatHistoryItem(role=m["role"], content=m["content"])
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
    user: dict = Depends(require_auth),
):
    page = max(1, page)
    page_size = min(max(1, page_size), 100)
    skip = (page - 1) * page_size

    repo = get_chat_history_repository()
    user_id = str(user.get("sub", ""))

    normalized_status_filter = (
        status_filter.strip().lower() if status_filter else repo.SESSION_STATUS_ACTIVE
    )
    valid_statuses = {
        repo.SESSION_STATUS_ACTIVE,
        repo.SESSION_STATUS_ARCHIVED,
    }
    if normalized_status_filter not in valid_statuses:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid status_filter. Allowed values: active, archived",
        )

    sessions, total = await repo.list_sessions_by_user(
        user_id=user_id,
        limit=page_size,
        skip=skip,
        status=normalized_status_filter,
    )

    items = [
        ChatSessionItem(
            session_id=s.get("session_id", ""),
            title=s.get("title"),
            status=s.get("status", "active"),
            message_count=int(s.get("message_count", 0)),
            last_message_at=to_iso_str(s.get("last_message_at")),
            created_at=to_iso_str(s.get("created_at")),
            updated_at=to_iso_str(s.get("updated_at")),
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
    user: dict = Depends(require_auth),
):
    page = max(1, page)
    page_size = min(max(1, page_size), 100)
    skip = (page - 1) * page_size

    repo = get_chat_history_repository()
    user_id = str(user.get("sub", ""))
    messages, total = await repo.list_messages_by_session(
        session_id=session_id,
        user_id=user_id,
        limit=page_size,
        skip=skip,
    )

    items = [
        ChatMessageItem(
            role=m.get("role", "assistant"),
            content=m.get("content", ""),
            sequence=int(m.get("sequence", 0)),
            message_type=m.get("message_type", "text"),
            token_usage=m.get("token_usage"),
            sources=m.get("sources"),
            steps=m.get("steps") or None,
            processing_time_ms=m.get("processing_time_ms"),
            created_at=to_iso_str(m.get("created_at")),
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
    user: dict = Depends(require_auth),
):
    repo = get_chat_history_repository()
    user_id = str(user.get("sub", ""))
    updated = await repo.rename_session(session_id=session_id, user_id=user_id, title=request.title)
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    return ChatSessionMutationResponse(session_id=session_id, success=True)


@router.post(
    "/sessions/{session_id}/archive",
    response_model=ChatSessionMutationResponse,
    summary="Archive a chat session",
)
async def archive_chat_session(
    session_id: str,
    user: dict = Depends(require_auth),
):
    repo = get_chat_history_repository()
    user_id = str(user.get("sub", ""))
    updated = await repo.archive_session(session_id=session_id, user_id=user_id)
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    return ChatSessionMutationResponse(session_id=session_id, success=True)


@router.post(
    "/sessions/{session_id}/unarchive",
    response_model=ChatSessionMutationResponse,
    summary="Unarchive a chat session",
)
async def unarchive_chat_session(
    session_id: str,
    user: dict = Depends(require_auth),
):
    repo = get_chat_history_repository()
    user_id = str(user.get("sub", ""))
    updated = await repo.unarchive_session(session_id=session_id, user_id=user_id)
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    return ChatSessionMutationResponse(session_id=session_id, success=True)


@router.delete(
    "/sessions/{session_id}",
    response_model=ChatSessionMutationResponse,
    summary="Delete a chat session and its messages",
)
async def delete_chat_session(
    session_id: str,
    user: dict = Depends(require_auth),
):
    repo = get_chat_history_repository()
    user_id = str(user.get("sub", ""))
    deleted = await repo.delete_session(session_id=session_id, user_id=user_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    return ChatSessionMutationResponse(session_id=session_id, success=True)


@router.post(
    "/retrieve-preview",
    response_model=ChatRetrievePreviewResponse,
    summary="Preview Qdrant retrieval results",
    description="Debug endpoint to inspect retrieved chunks and ranking before generation.",
)
async def chat_retrieve_preview(
    request: ChatRetrievePreviewRequest,
    user: dict = Depends(require_auth),
):
    """Preview semantic retrieval result list for relevance tuning."""
    try:
        user_role = user.get("role", "student")

        retrieval = get_retrieval_service()

        meta_dict = request.metadata_filter.model_dump() if request.metadata_filter else {}

        qdrant_meta_filter = await retrieval._filter_builder.build_qdrant_filter(
            metadata_filter=meta_dict,
            user_role=user_role
        )

        chunks = await retrieval._qdrant.retrieve(
            query=request.question,
            top_k=request.top_k,
            min_score=request.min_score,
            metadata_filter=qdrant_meta_filter,
        )

        items = [
            ChatRetrievePreviewItem(
                rank=i,
                file_id=c.get("file_id"),
                file_name=c.get("file_name"),
                section_path=c.get("section_path"),
                score=c.get("_retrieval_score"),
                explain=c.get("_retrieval_explain") if request.include_explain else None,
                text=c.get("text") or "",
            )
            for i, c in enumerate(chunks, start=1)
        ]

        return ChatRetrievePreviewResponse(
            query=request.question,
            top_k=request.top_k or settings.QDRANT_TOP_K,
            min_score=(
                float(request.min_score)
                if request.min_score is not None
                else float(settings.QDRANT_MIN_SCORE)
            ),
            count=len(items),
            cache_stats=None,
            items=items,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except APIError as e:
        raise handle_google_api_error(e, prefix="Failed to preview Qdrant retrieval: ")
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to preview Qdrant retrieval: {str(e)}",
        )
