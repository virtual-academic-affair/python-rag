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

logger = logging.getLogger(__name__)


from app.modules.chat.schemas import (
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
from app.modules.chat.service import get_chat_service
from app.modules.chat.history_repository import get_chat_history_repository
from app.modules.rag.retrieval.service import get_retrieval_service
from app.core.config import settings
from app.core.exceptions import handle_google_api_error

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

    **Use Case:** Non-streaming chat responses with document retrieval.

    **Flow:**
    1. Receive question + student context + chat history
    2. Use internal Qdrant semantic retrieval
    3. Return complete answer with sources and token usage

    **Note:**
    - RAG Service does NOT manage sessions. Chat history must be sent from NestJS.
    """
    try:
        # Extract role from token and override context
        user_role = user.get("role", "student")

        # Extract enrollment_year from JWT if present
        jwt_enrollment = user.get("enrollmentyear") or user.get("enrollment_year")
        enrollment_year = None
        if jwt_enrollment:
            try:
                if isinstance(jwt_enrollment, str):
                    import re
                    match = re.search(r"\d+", jwt_enrollment)
                    if match:
                        val = int(match.group())
                        enrollment_year = 2000 + val if val < 100 else val
                    else:
                        enrollment_year = int(jwt_enrollment)
                else:
                    val = int(jwt_enrollment)
                    enrollment_year = 2000 + val if val < 100 else val
            except Exception as e:
                logger.warning(f"Failed to parse enrollmentyear from JWT '{jwt_enrollment}': {e}")

        # Build user context from auth token
        user_context = UserContext(
            user_id=str(user.get("sub", "")),
            name=user.get("email", "").split("@")[0] if user.get("email") else "Unknown",
            enrollment_year=enrollment_year,
            role=user_role,
        )

        session_id = request.session_id or str(uuid4())

        chat_history_repo = get_chat_history_repository()
        await chat_history_repo.ensure_session(session_id=session_id, user_id=user_context.user_id)

        # Load history from DB
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

        # Generate response using unified retrieval service
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

    **Use Case:** Progressive response display for better UX with document retrieval.

    **Response Format:** Server-Sent Events (SSE)
    - Text chunks: `{"chunk": "text", "done": false}`
    - Final message: `{"done": true, "sources": [...], "token_usage": {...}, "processing_time_ms": 1234}`

    **Note:**
    - NestJS can forward this stream to WebSocket clients.
    """
    try:
        # Extract role from token and override context
        user_role = user.get("role", "student")

        # Extract enrollment_year from JWT if present
        jwt_enrollment = user.get("enrollmentyear") or user.get("enrollment_year")
        enrollment_year = None
        if jwt_enrollment:
            try:
                if isinstance(jwt_enrollment, str):
                    import re
                    match = re.search(r"\d+", jwt_enrollment)
                    if match:
                        val = int(match.group())
                        enrollment_year = 2000 + val if val < 100 else val
                    else:
                        enrollment_year = int(jwt_enrollment)
                else:
                    val = int(jwt_enrollment)
                    enrollment_year = 2000 + val if val < 100 else val
            except Exception as e:
                logger.warning(f"Failed to parse enrollmentyear from JWT '{jwt_enrollment}': {e}")

        # Build user context from auth token
        user_context = UserContext(
            user_id=str(user.get("sub", "")),
            name=user.get("email", "").split("@")[0] if user.get("email") else "Unknown",
            enrollment_year=enrollment_year,
            role=user_role,
        )

        session_id = request.session_id or str(uuid4())
        chat_history_repo = get_chat_history_repository()
        await chat_history_repo.ensure_session(session_id=session_id, user_id=user_context.user_id)

        # Load history from DB
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
            """Generator for SSE events."""
            assistant_chunks: list[str] = []
            thought_chunks: list[str] = []
            try:
                chat_svc = get_chat_service()
                async for chunk_json in chat_svc.stream_chat_response(
                    question=request.question,
                    user_context=user_context,
                    chat_history=chat_history,
                    resolve_citations=request.resolve_citations,
                    citation_link_type=request.citation_link_type,
                ):
                    payload = json.loads(chunk_json)
                    if payload.get("type") == "thought" and payload.get("content"):
                        thought_chunks.append(payload["content"])
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

                        thought_content = "\n".join(thought_chunks).strip()
                        if thought_content:
                            await chat_history_repo.append_message(
                                session_id=session_id,
                                user_id=user_context.user_id,
                                role="assistant",
                                content=thought_content,
                                message_type="thinking",
                            )

                        await chat_history_repo.append_message(
                            session_id=session_id,
                            user_id=user_context.user_id,
                            role="assistant",
                            content=assistant_content,
                            token_usage=payload.get("token_usage") or payload.get("tokenUsage"),
                            sources=payload.get("sources"),
                            steps=payload.get("steps"),
                            processing_time_ms=payload.get("processing_time_ms"),
                            message_type="text",
                        )
                        payload["session_id"] = session_id
                        chunk_json = json.dumps(payload, ensure_ascii=False)
                    # SSE format: data: {json}\n\n
                    yield f"data: {chunk_json}\n\n"
            except ValueError as e:
                error_data = json.dumps({
                    "error": str(e),
                    "done": True
                })
                yield f"data: {error_data}\n\n"
            except APIError as e:
                ai_code = getattr(e, "code", 500)
                if not isinstance(ai_code, int) or ai_code < 400:
                    ai_code = 500
                if ai_code == 429:
                    error_data = json.dumps({
                        "error": "rate_limit_exceeded",
                        "message": "Quá tải hệ thống AI. Vui lòng thử lại sau.",
                        "status_code": 429,
                        "done": True
                    })
                elif ai_code == 500 and ("500 INTERNAL" in str(e) or "Internal error encountered" in str(e)):
                    error_data = json.dumps({
                        "error": "ai_service_error",
                        "message": "Google internal server error",
                        "status_code": 500,
                        "done": True
                    })
                else:
                    error_data = json.dumps({
                        "error": "ai_service_error",
                        "message": str(e),
                        "status_code": ai_code,
                        "done": True
                    })
                yield f"data: {error_data}\n\n"
            except Exception as e:
                error_data = json.dumps({
                    "error": "internal_error",
                    "message": f"Failed to stream chat response: {str(e)}",
                    "done": True
                })
                yield f"data: {error_data}\n\n"

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",  # Disable nginx buffering
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
            last_message_at=s.get("last_message_at").isoformat() if s.get("last_message_at") else None,
            created_at=s.get("created_at").isoformat() if s.get("created_at") else None,
            updated_at=s.get("updated_at").isoformat() if s.get("updated_at") else None,
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
            created_at=m.get("created_at").isoformat() if m.get("created_at") else None,
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
        meta_dict = request.metadata_filter or {}

        user_role = user.get("role", "student")

        # Note: Using unified RetrievalService for preview to see context as processed by RAG
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
