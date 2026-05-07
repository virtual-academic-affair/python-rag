"""
Chat Endpoints - Handle all RAG-based chat operations.
Includes: query, stream, and retrieval preview (Qdrant).
"""

from fastapi import APIRouter, HTTPException, status, Depends
from fastapi.responses import StreamingResponse
import json


from app.modules.chat.schemas import (
    ChatQueryRequest,
    ChatQueryResponse,
    ChatStreamRequest,
    UserContext,
    ChatRetrievePreviewRequest,
    ChatRetrievePreviewResponse,
    ChatRetrievePreviewItem,
)
from app.core.dependencies import require_auth
from app.modules.chat.service import get_chat_service
from app.modules.rag.retrieval.service import get_retrieval_service
from app.core.config import settings
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
        # Use metadata_filter as provided by the client
        meta_dict = request.metadata_filter or {}

        # Extract role from token and override context
        user_role = user.get("role", "student")

        # Build user context from auth token
        user_context = UserContext(
            user_id=str(user.get("sub", "")),
            name=user.get("email", "").split("@")[0] if user.get("email") else "Unknown",
            enrollment_year=None, # TBD: extract from cohort/class if needed
            role=user_role,
        )

        # Generate response using unified retrieval service
        chat_svc = get_chat_service()
        result = await chat_svc.generate_chat_response(
            question=request.question,
            user_context=user_context,
            chat_history=request.chat_history,
            metadata_filter=request.metadata_filter,
        )

        return ChatQueryResponse(**result)

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        error_msg = str(e)
        if "500 INTERNAL" in error_msg or "Internal error encountered" in error_msg:
            detail_msg = "Failed to generate chat response: Google internal server error"
        else:
            detail_msg = f"Failed to generate chat response: {error_msg}"
            
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=detail_msg,
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
        # Use metadata_filter as provided by the client
        meta_dict = request.metadata_filter or {}

        # Extract role from token and override context
        user_role = user.get("role", "student")

        # Build user context from auth token
        user_context = UserContext(
            user_id=str(user.get("sub", "")),
            name=user.get("email", "").split("@")[0] if user.get("email") else "Unknown",
            enrollment_year=None,
            role=user_role,
        )

        async def event_generator():
            """Generator for SSE events."""
            try:
                chat_svc = get_chat_service()
                async for chunk_json in chat_svc.stream_chat_response(
                    question=request.question,
                    user_context=user_context,
                    chat_history=request.chat_history,
                    metadata_filter=request.metadata_filter,
                ):
                    # SSE format: data: {json}\n\n
                    yield f"data: {chunk_json}\n\n"
            except ValueError as e:
                error_data = json.dumps({
                    "error": str(e),
                    "done": True
                })
                yield f"data: {error_data}\n\n"
            except Exception as e:
                error_msg = str(e)
                if "500 INTERNAL" in error_msg or "Internal error encountered" in error_msg:
                    error_msg = "Failed to stream chat response: Google internal server error"
                error_data = json.dumps({
                    "error": error_msg,
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
    except Exception as e:
        error_msg = str(e)
        if "500 INTERNAL" in error_msg or "Internal error encountered" in error_msg:
            detail_msg = "Failed to stream chat response: Google internal server error"
        else:
            detail_msg = f"Failed to stream chat response: {error_msg}"
            
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=detail_msg,
        )


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
    except Exception as e:
        error_msg = str(e)
        if "500 INTERNAL" in error_msg or "Internal error encountered" in error_msg:
            detail_msg = "Failed to preview Qdrant retrieval: Google internal server error"
        else:
            detail_msg = f"Failed to preview Qdrant retrieval: {error_msg}"
            
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=detail_msg,
        )
