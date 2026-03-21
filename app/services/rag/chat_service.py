"""
Chat Service - Handles RAG-based chat operations (generate/stream).
"""
import asyncio
import json
import time
import queue
from typing import Optional, AsyncGenerator

from google.genai import types

from app.core.config import settings
from app.core.prompts import (
    CHAT_SYSTEM_PROMPT,
    CHAT_WITH_CONTEXT_TEMPLATE,
)
from app.models.schemas import ChatHistoryItem, UserContext
from app.repositories.file_repository import FileRepository
from app.services.rag.gemini_client import gemini_client
from app.services.rag.utils.gemini_rag_utils import (
    format_chat_history,
    extract_sources,
    inject_citations,
    enrich_sources_with_urls,
    extract_token_usage
)


class ChatService:
    """
    Service for RAG-based chat operations using Gemini.
    """
    
    def __init__(self):
        self._file_repo = None

    @property
    def file_repo(self) -> FileRepository:
        """Lazy load file repository."""
        if self._file_repo is None:
            self._file_repo = FileRepository()
        return self._file_repo

    async def generate_chat_response(
        self,
        question: str,
        user_context: UserContext,
        chat_history: list[ChatHistoryItem],
        store_name: Optional[str] = None,
        metadata_filter: Optional[str] = None,
    ) -> dict:
        """
        Generate a chat response using Gemini with RAG (File Search).
        """
        if not store_name:
            raise ValueError("store_name is required. RAG Service requires File Search for all chat operations.")
        
        start_time = time.time()
        
        # Build the full prompt with context
        history_text = format_chat_history(chat_history)
        full_prompt = CHAT_WITH_CONTEXT_TEMPLATE.format(
            student_name=user_context.name,
            student_id=user_context.user_id,
            cohort=user_context.cohort,
            chat_history=history_text,
            current_question=question,
        )
        
        # Prepare generation config
        config = types.GenerateContentConfig(
            temperature=settings.GEMINI_TEMPERATURE,
            max_output_tokens=settings.GEMINI_MAX_OUTPUT_TOKENS,
            top_p=settings.GEMINI_TOP_P,
            top_k=settings.GEMINI_TOP_K,
            system_instruction=CHAT_SYSTEM_PROMPT,
        )
        
        # Add File Search tool
        file_search_config = types.FileSearch(
            fileSearchStoreNames=[store_name],
            metadataFilter=metadata_filter
        )
        
        config.tools = [
            types.Tool(fileSearch=file_search_config)
        ]
        
        # Native async Gemini call
        response = await gemini_client.client.aio.models.generate_content(
            model=settings.GEMINI_MODEL,
            contents=full_prompt,
            config=config,
        )
        
        processing_time_ms = int((time.time() - start_time) * 1000)
        
        # Extract answer
        answer = response.text if hasattr(response, "text") else ""
        
        # Extract sources from grounding metadata
        sources, chunk_map = extract_sources(response)
        
        # Inject citations
        if answer and chunk_map:
            answer = inject_citations(answer, response, chunk_map)
        
        # Enrich sources with download URLs
        sources = await enrich_sources_with_urls(sources, self.file_repo)
        
        # Extract token usage
        token_usage = extract_token_usage(response)
        
        return {
            "answer": answer,
            "sources": sources,
            "token_usage": token_usage,
            "processing_time_ms": processing_time_ms,
        }
    
    async def stream_chat_response(
        self,
        question: str,
        user_context: UserContext,
        chat_history: list[ChatHistoryItem],
        store_name: Optional[str] = None,
        metadata_filter: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        """
        Stream chat response using Server-Sent Events (SSE) with RAG.
        Uses native async streaming.
        """
        if not store_name:
            raise ValueError("store_name is required. RAG Service requires File Search for all chat operations.")
        
        start_time = time.time()
        
        history_text = format_chat_history(chat_history)
        full_prompt = CHAT_WITH_CONTEXT_TEMPLATE.format(
            student_name=user_context.name,
            student_id=user_context.user_id,
            cohort=user_context.cohort,
            chat_history=history_text,
            current_question=question,
        )
        
        config = types.GenerateContentConfig(
            temperature=settings.GEMINI_TEMPERATURE,
            max_output_tokens=settings.GEMINI_MAX_OUTPUT_TOKENS,
            system_instruction=CHAT_SYSTEM_PROMPT,
        )
        
        # Add File Search tool
        file_search_config = types.FileSearch(
            fileSearchStoreNames=[store_name],
            metadataFilter=metadata_filter
        )
        
        config.tools = [
            types.Tool(fileSearch=file_search_config)
        ]
        
        all_chunks = []
        
        # Native async Gemini streaming
        stream = await gemini_client.client.aio.models.generate_content_stream(
            model=settings.GEMINI_MODEL,
            contents=full_prompt,
            config=config,
        )

        async for chunk in stream:
            all_chunks.append(chunk)
            if hasattr(chunk, "text") and chunk.text:
                yield json.dumps({"chunk": chunk.text, "done": False})
        
        # Collect sources and usage from final aggregated state or chunks
        all_sources = []
        token_usage = {}
        
        for chunk in all_chunks:
            chunk_sources, _ = extract_sources(chunk)
            if chunk_sources:
                all_sources.extend(chunk_sources)
            
            chunk_usage = extract_token_usage(chunk)
            if chunk_usage:
                token_usage = chunk_usage
        
        seen = set()
        unique_sources = []
        for source in all_sources:
            key = source.get("title")
            if key not in seen:
                seen.add(key)
                unique_sources.append(source)
        
        unique_sources = await enrich_sources_with_urls(unique_sources, self.file_repo)
        
        processing_time_ms = int((time.time() - start_time) * 1000)
        
        yield json.dumps({
            "done": True,
            "sources": unique_sources if unique_sources else None,
            "token_usage": token_usage if token_usage else None,
            "processing_time_ms": processing_time_ms,
        })

_chat_service_instance: Optional[ChatService] = None

def get_chat_service() -> ChatService:
    """Get singleton instance of ChatService."""
    global _chat_service_instance
    if _chat_service_instance is None:
        _chat_service_instance = ChatService()
    return _chat_service_instance

chat_service = get_chat_service()
