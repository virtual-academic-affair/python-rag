"""
Chat Endpoints - Handle all RAG-based chat operations.
Includes: query and stream.
All chat operations require File Search store for RAG.
"""

from fastapi import APIRouter, HTTPException, status, Depends
from fastapi.responses import StreamingResponse
import json

from app.models.schemas import (
    ChatQueryRequest,
    ChatQueryResponse,
    ChatStreamRequest,
    UserContext
)
from app.dependencies.auth import require_auth
from app.services.rag.chat_service import chat_service
from app.services.rag.utils.store_utils import resolve_store
from app.services.rag.utils.filter_builder import build_metadata_filter
from app.services.rag.utils.file_utils import convert_custom_metadata_to_snake


router = APIRouter(prefix="/chat", tags=["Chat"])


@router.post(
    "/query",
    response_model=ChatQueryResponse,
    summary="Generate RAG-based chat response",
    description="Process a user question with RAG (File Search) and return a complete answer.",
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
    2. **REQUIRED**: Use Gemini File Search for document retrieval
    3. Return complete answer with sources and token usage
    
    **Note:** 
    - RAG Service does NOT manage sessions. Chat history must be sent from NestJS.
    - If store_id is not provided, uses default store from database.
    """
    try:
        # Resolve store (request → default store → error)
        # Always use default store unless system design changes
        store_id, store_name = await resolve_store(None)
        
        # Convert metadata filter keys from camelCase to snake_case
        meta_dict = request.metadata_filter or {}
        if meta_dict:
            meta_dict = convert_custom_metadata_to_snake(meta_dict)
            
        # Extract role from token and override context
        user_role = user.get("role", "student")
        
        # Build user context from auth token
        user_context = UserContext(
            user_id=str(user.get("sub", "")),
            name=user.get("email", "").split("@")[0] if user.get("email") else "Unknown",
            cohort="Unknown", # Requires further alignment if cohort is needed from token
            role=user_role
        )
            
        # Build metadata filter with role enforcement and validation
        metadata_filter = await build_metadata_filter(
            metadata=meta_dict,
            user_role=user_role
        )
        
        # Generate response using Gemini service
        result = await chat_service.generate_chat_response(
            question=request.question,
            user_context=user_context,
            chat_history=request.chat_history,
            store_name=store_name,
            metadata_filter=metadata_filter,
        )
        
        return ChatQueryResponse(**result)
    
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
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
    - If store_id is not provided, uses default store from database.
    """
    try:
        # Resolve store (request → default store → error)
        # Always use default store unless system design changes
        store_id, store_name = await resolve_store(None)
        
        # Convert metadata filter keys from camelCase to snake_case
        meta_dict = request.metadata_filter or {}
        if meta_dict:
            meta_dict = convert_custom_metadata_to_snake(meta_dict)
            
        # Extract role from token and override context
        user_role = user.get("role", "student")
        
        # Build user context from auth token
        user_context = UserContext(
            user_id=str(user.get("sub", "")),
            name=user.get("email", "").split("@")[0] if user.get("email") else "Unknown",
            cohort="Unknown", # Requires further alignment if cohort is needed from token
            role=user_role
        )
            
        # Build metadata filter with role enforcement and validation
        metadata_filter = await build_metadata_filter(
            metadata=meta_dict,
            user_role=user_role
        )
        
        async def event_generator():
            """Generator for SSE events."""
            try:
                async for chunk_json in chat_service.stream_chat_response(
                    question=request.question,
                    user_context=user_context,
                    chat_history=request.chat_history,
                    store_name=store_name,
                    metadata_filter=metadata_filter,
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
                error_data = json.dumps({
                    "error": str(e),
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
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to stream chat response: {str(e)}",
        )
