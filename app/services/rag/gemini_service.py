"""
Gemini Service - Singleton wrapper for Google Generative AI SDK.
Handles all interactions with Gemini API for RAG-based chat and email operations.
"""

import asyncio
import json
import time
from typing import Optional, AsyncGenerator
from google import genai
from google.genai import types

from app.core.config import settings
from app.core.prompts import (
    CHAT_SYSTEM_PROMPT,
    CHAT_WITH_CONTEXT_TEMPLATE,
    EMAIL_DRAFT_REPLY_PROMPT,
)
from app.models.schemas import (
    ChatHistoryItem,
    UserContext,
)
from app.repositories.file_repository import FileRepository


class GeminiService:
    """
    Singleton service for Gemini API interactions.
    Provides async methods for RAG-based chat, streaming, and email reply generation.
    All operations use Gemini File Search for document retrieval.
    """
    
    _instance: Optional["GeminiService"] = None
    _client: Optional[genai.Client] = None
    _file_repo: Optional[FileRepository] = None
    
    def __new__(cls):
        """Singleton pattern implementation."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        """Initialize Gemini client (only once)."""
        if self._client is None:
            self._client = genai.Client(api_key=settings.GOOGLE_API_KEY)
    
    @property
    def file_repo(self) -> FileRepository:
        """Get FileRepository instance (lazy initialization)."""
        if self._file_repo is None:
            self._file_repo = FileRepository()
        return self._file_repo
    
    @property
    def client(self) -> genai.Client:
        """Get the Gemini client instance."""
        if self._client is None:
            raise RuntimeError("Gemini client not initialized")
        return self._client
    
    # ====================================
    # CHAT METHODS
    # ====================================
    
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
        
        Args:
            question: User's question
            user_context: User information
            chat_history: Recent conversation history (5-10 messages)
            store_name: File Search store name for RAG (REQUIRED)
            metadata_filter: Metadata filter string (e.g., 'department=IT AND category=policy')
        
        Returns:
            dict with 'answer', 'sources', 'token_usage'
        
        Raises:
            ValueError: If store_name is not provided (RAG required)
        """
        if not store_name:
            raise ValueError("store_name is required. RAG Service requires File Search for all chat operations.")
        
        start_time = time.time()
        
        # Build the full prompt with context
        history_text = self._format_chat_history(chat_history)
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
        
        # Add File Search tool (REQUIRED for RAG Service)
        if metadata_filter:
            file_search_config = types.FileSearch(
                fileSearchStoreNames=[store_name],
                metadataFilter=metadata_filter
            )
        else:
            file_search_config = types.FileSearch(
                fileSearchStoreNames=[store_name]
            )
        
        config.tools = [
            types.Tool(fileSearch=file_search_config)
        ]
        
        # Run in executor to avoid blocking
        response = await asyncio.to_thread(
            self.client.models.generate_content,
            model=settings.GEMINI_MODEL,
            contents=full_prompt,
            config=config,
        )
        
        processing_time_ms = int((time.time() - start_time) * 1000)
        
        # Extract answer
        answer = response.text if hasattr(response, "text") else ""
        
        # Extract sources from grounding metadata
        sources = self._extract_sources(response)
        
        # Enrich sources with download URLs
        sources = await self._enrich_sources_with_urls(sources)
        
        # Extract token usage
        token_usage = self._extract_token_usage(response)
        
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
        
        Args:
            question: User's question
            user_context: User information
            chat_history: Recent conversation history
            store_name: File Search store name (REQUIRED)
            metadata_filter: Metadata filter for File Search
        
        Yields:
            JSON strings with chunks of the response
        
        Raises:
            ValueError: If store_name is not provided
        """
        if not store_name:
            raise ValueError("store_name is required. RAG Service requires File Search for all chat operations.")
        
        start_time = time.time()
        
        history_text = self._format_chat_history(chat_history)
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
        
        # Add File Search tool (REQUIRED)
        if metadata_filter:
            file_search_config = types.FileSearch(
                fileSearchStoreNames=[store_name],
                metadataFilter=metadata_filter
            )
        else:
            file_search_config = types.FileSearch(
                fileSearchStoreNames=[store_name]
            )
        
        config.tools = [
            types.Tool(fileSearch=file_search_config)
        ]
        
        # Stream response — run blocking iterator in thread, bridge via queue
        import queue
        chunk_queue: queue.Queue = queue.Queue()
        _SENTINEL = object()

        def _stream_in_thread():
            try:
                stream = self.client.models.generate_content_stream(
                    model=settings.GEMINI_MODEL,
                    contents=full_prompt,
                    config=config,
                )
                for chunk in stream:
                    chunk_queue.put(chunk)
            except Exception as exc:
                chunk_queue.put(exc)
            finally:
                chunk_queue.put(_SENTINEL)

        stream_thread = asyncio.get_event_loop().run_in_executor(None, _stream_in_thread)
        
        # Store all chunks for complete metadata extraction
        all_chunks = []
        
        while True:
            item = await asyncio.to_thread(chunk_queue.get)
            if item is _SENTINEL:
                break
            if isinstance(item, Exception):
                raise item
            chunk = item
            all_chunks.append(chunk)
            if hasattr(chunk, "text") and chunk.text:
                yield json.dumps({"chunk": chunk.text, "done": False})
        
        await stream_thread
        
        # Extract and aggregate metadata from all chunks
        all_sources = []
        token_usage = {}
        
        for chunk in all_chunks:
            # Extract sources from each chunk
            chunk_sources = self._extract_sources(chunk)
            if chunk_sources:
                all_sources.extend(chunk_sources)
            
            # Token usage typically in the last chunk, but check all
            chunk_usage = self._extract_token_usage(chunk)
            if chunk_usage:
                token_usage = chunk_usage
        
        # Remove duplicate sources (same title)
        seen = set()
        unique_sources = []
        for source in all_sources:
            key = source.get("title")
            if key not in seen:
                seen.add(key)
                unique_sources.append(source)
        
        # Enrich sources with download URLs
        unique_sources = await self._enrich_sources_with_urls(unique_sources)
        
        processing_time_ms = int((time.time() - start_time) * 1000)
        
        # Final message with metadata
        yield json.dumps({
            "done": True,
            "sources": unique_sources if unique_sources else None,
            "token_usage": token_usage if token_usage else None,
            "processing_time_ms": processing_time_ms,
        })
    
    # ====================================
    # EMAIL METHODS (RAG-BASED)
    # ====================================
    
    async def draft_email_reply(
        self,
        original_subject: str,
        original_body: str,
        sender_name: Optional[str] = None,
        additional_context: Optional[str] = None,
        store_name: Optional[str] = None,
        metadata_filter: Optional[str] = None,
    ) -> dict:
        """
        Draft a professional email reply using RAG.
        
        Args:
            original_subject: Original email subject
            original_body: Original email body
            sender_name: Sender's name
            additional_context: Extra instructions
            store_name: File Search store for RAG (REQUIRED)
            metadata_filter: Metadata filter for File Search (e.g., 'department=IT')
        
        Returns:
            dict with 'draft_subject', 'draft_body'
        
        Raises:
            ValueError: If store_name is not provided
        """
        if not store_name:
            raise ValueError("store_name is required. RAG Service requires File Search for email replies.")
        
        prompt_parts = [
            EMAIL_DRAFT_REPLY_PROMPT,
            f"\n**EMAIL GỐC:**",
            f"Subject: {original_subject}",
            f"Body:\n{original_body}",
        ]
        
        if sender_name:
            prompt_parts.append(f"\n**Người gửi:** {sender_name}")
        
        if additional_context:
            prompt_parts.append(f"\n**Chỉ dẫn thêm:** {additional_context}")
        
        full_prompt = "\n".join(prompt_parts)
        
        config = types.GenerateContentConfig(
            temperature=0.7,
            max_output_tokens=1500,
        )
        
        # Add File Search tool (REQUIRED for RAG Service)
        file_search_config = types.FileSearch(
            fileSearchStoreNames=[store_name]
        )
        
        # Add metadata filter if provided
        if metadata_filter:
            file_search_config = types.FileSearch(
                fileSearchStoreNames=[store_name],
                metadataFilter=metadata_filter
            )
        
        config.tools = [
            types.Tool(fileSearch=file_search_config)
        ]
        
        response = await asyncio.to_thread(
            self.client.models.generate_content,
            model=settings.GEMINI_MODEL,
            contents=full_prompt,
            config=config,
        )
        
        draft_body = response.text or ""
        
        # Extract subject from draft (usually starts with "Re:")
        draft_subject = f"Re: {original_subject}"
        
        # Extract sources from grounding metadata (same as chat)
        sources = self._extract_sources(response) or []
        
        # Enrich sources with download URLs
        sources = await self._enrich_sources_with_urls(sources) or []
        
        return {
            "draft_subject": draft_subject,
            "draft_body": draft_body,
            "sources": sources,
            "token_usage": self._extract_token_usage(response),
        }
    
    # ====================================
    # HELPER METHODS
    # ====================================
    
    def _format_chat_history(self, history: list[ChatHistoryItem]) -> str:
        """Format chat history into readable text."""
        if not history:
            return "(Chưa có lịch sử hội thoại)"
        
        formatted = []
        for msg in history:
            role_name = "Sinh viên" if msg.role == "user" else "Trợ lý"
            formatted.append(f"{role_name}: {msg.content}")
        
        return "\n".join(formatted)
    
    def _extract_sources(self, response) -> Optional[list[dict]]:
        """Extract document sources from grounding metadata with full details."""
        citations = []
        
        if not hasattr(response, "candidates") or not response.candidates:
            return None
        
        candidate = response.candidates[0]
        
        if hasattr(candidate, "grounding_metadata") and candidate.grounding_metadata:
            metadata = candidate.grounding_metadata
            
            # Extract from grounding_chunks (File Search results)
            if hasattr(metadata, "grounding_chunks"):
                for chunk in metadata.grounding_chunks:
                    # Check for retrieved_context (File Search)
                    if hasattr(chunk, "retrieved_context"):
                        ctx = chunk.retrieved_context
                        citation = {}
                        
                        # Extract title/document name
                        if hasattr(ctx, "title") and ctx.title:
                            citation["title"] = ctx.title
                        
                        # Extract text excerpt
                        if hasattr(ctx, "text") and ctx.text:
                            citation["text"] = ctx.text
                        
                        # Only add if we have at least some info
                        if citation:
                            citations.append(citation)
                    
                    # Fallback: Check for web sources
                    elif hasattr(chunk, "web") and chunk.web:
                        web_citation = {}
                        if hasattr(chunk.web, "title"):
                            web_citation["title"] = chunk.web.title
                        if web_citation:
                            citations.append(web_citation)
        
        # Remove duplicate citations (same title)
        seen = set()
        unique_citations = []
        for citation in citations:
            key = citation.get("title")
            if key not in seen:
                seen.add(key)
                unique_citations.append(citation)
        
        return unique_citations if unique_citations else None
    
    async def _enrich_sources_with_urls(self, sources: Optional[list[dict]]) -> Optional[list[dict]]:
        """
        Enrich sources with download URLs by looking up files in database.
        
        Args:
            sources: List of source citations with title and text
            
        Returns:
            Enriched sources with url field added
        """
        if not sources:
            return sources
        
        # Collect all titles to look up
        titles = [s.get("title") for s in sources if s.get("title")]
        if not titles:
            return sources
        
        # Look up files by display_name
        try:
            files = await self.file_repo.find_by_display_names(titles)
        except Exception:
            return sources
        
        # Create a map of display_name -> file info
        file_map = {}
        for f in files:
            display_name = f.get("display_name")
            if display_name:
                file_map[display_name] = {
                    "file_id": str(f.get("_id")),
                    "storage_path": f.get("storage_path"),
                }
        
        # Enrich sources with presigned URLs
        from app.storage.minio_client import minio_storage
        
        for source in sources:
            title = source.get("title")
            if title and title in file_map:
                file_info = file_map[title]
                path = file_info["storage_path"]
                if path:
                    try:
                        source["url"] = await minio_storage.get_file_url(path)
                    except Exception:
                        pass
                source["file_id"] = file_info["file_id"]
        
        return sources
    
    def _extract_token_usage(self, response) -> Optional[dict]:
        """Extract token usage statistics from response."""
        usage = None
        
        if hasattr(response, "usage_metadata") and response.usage_metadata:
            usage = response.usage_metadata
        elif hasattr(response, "candidates") and response.candidates:
            c = response.candidates[0]
            if hasattr(c, "usage_metadata") and c.usage_metadata:
                usage = c.usage_metadata
        
        if not usage:
            return None
        
        return {
            "prompt_tokens": getattr(usage, "prompt_token_count", 0),
            "output_tokens": getattr(usage, "candidates_token_count", 0),
            "total_tokens": getattr(usage, "total_token_count", 0),
        }


# Singleton instance
gemini_service = GeminiService()
