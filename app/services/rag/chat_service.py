"""
Chat Service - Handles RAG-based chat operations (generate/stream).
"""
import json
import time
from typing import Optional, AsyncGenerator, Any

from google.genai import types

from app.core.config import settings
from app.core.prompts import CHAT_SYSTEM_PROMPT, CHAT_WITH_CONTEXT_TEMPLATE
from app.models.schemas import ChatHistoryItem, UserContext
from app.repositories.file_repository import FileRepository
from app.services.rag.gemini_client import gemini_client
from app.services.rag.utils.gemini_rag_utils import format_chat_history, enrich_sources_with_urls, extract_token_usage
from app.services.rag.vectorless_retrieval_service import get_vectorless_retrieval_service


class ChatService:
    """Service for RAG-based chat operations using Gemini + vectorless retrieval."""

    def __init__(self):
        self._file_repo = None
        self._retrieval = get_vectorless_retrieval_service()

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
        metadata_filter: Optional[dict[str, Any]] = None,
    ) -> dict:
        """Generate chat response using vectorless retrieval (no Gemini File Search)."""
        start_time = time.time()

        retrieved_chunks = await self._retrieval.retrieve(
            query=question,
            top_k=settings.VECTORLESS_TOP_K,
            min_score=settings.VECTORLESS_MIN_SCORE,
            metadata_filter=metadata_filter,
            user_role=user_context.role,
        )

        context_blocks = []
        citations = []
        for idx, c in enumerate(retrieved_chunks, start=1):
            context_blocks.append(
                f"[{idx}] (file={c.get('file_name','Unknown')}, page={c.get('page_index_start',0)}-{c.get('page_index_end',0)})\n{c.get('text','')}"
            )
            citations.append(
                {
                    "citation_id": idx,
                    "title": c.get("file_name"),
                    "text": c.get("text"),
                    "file_id": c.get("file_id"),
                    "page_index_start": c.get("page_index_start"),
                    "page_index_end": c.get("page_index_end"),
                }
            )

        history_text = format_chat_history(chat_history)
        base_prompt = CHAT_WITH_CONTEXT_TEMPLATE.format(
            student_name=user_context.name,
            student_id=user_context.user_id,
            cohort=user_context.cohort,
            chat_history=history_text,
            current_question=question,
        )
        full_prompt = (
            base_prompt
            + "\n\n**NGỮ CẢNH TRUY XUẤT (VECTORLESS):**\n"
            + ("\n\n".join(context_blocks) if context_blocks else "(Không tìm thấy đoạn phù hợp)")
            + "\n\nHãy trả lời dựa trên ngữ cảnh ở trên. Nếu thiếu thông tin thì nói rõ."
        )

        config = types.GenerateContentConfig(
            temperature=settings.GEMINI_TEMPERATURE,
            max_output_tokens=settings.GEMINI_MAX_OUTPUT_TOKENS,
            top_p=settings.GEMINI_TOP_P,
            top_k=settings.GEMINI_TOP_K,
            system_instruction=CHAT_SYSTEM_PROMPT,
        )

        response = await gemini_client.client.aio.models.generate_content(
            model=settings.GEMINI_MODEL,
            contents=full_prompt,
            config=config,
        )

        answer = response.text if hasattr(response, "text") else ""
        token_usage = extract_token_usage(response)

        sources = await enrich_sources_with_urls(citations, self.file_repo)

        return {
            "answer": answer,
            "sources": sources,
            "token_usage": token_usage,
            "processing_time_ms": int((time.time() - start_time) * 1000),
        }

    async def stream_chat_response(
        self,
        question: str,
        user_context: UserContext,
        chat_history: list[ChatHistoryItem],
        store_name: Optional[str] = None,
        metadata_filter: Optional[dict[str, Any]] = None,
    ) -> AsyncGenerator[str, None]:
        """Stream chat response with vectorless retrieval context."""
        start_time = time.time()

        retrieved_chunks = await self._retrieval.retrieve(
            query=question,
            top_k=settings.VECTORLESS_TOP_K,
            min_score=settings.VECTORLESS_MIN_SCORE,
            metadata_filter=metadata_filter,
            user_role=user_context.role,
        )

        context_blocks = []
        citations = []
        for idx, c in enumerate(retrieved_chunks, start=1):
            context_blocks.append(
                f"[{idx}] (file={c.get('file_name','Unknown')}, page={c.get('page_index_start',0)}-{c.get('page_index_end',0)})\n{c.get('text','')}"
            )
            citations.append(
                {
                    "citation_id": idx,
                    "title": c.get("file_name"),
                    "text": c.get("text"),
                    "file_id": c.get("file_id"),
                    "page_index_start": c.get("page_index_start"),
                    "page_index_end": c.get("page_index_end"),
                }
            )

        history_text = format_chat_history(chat_history)
        base_prompt = CHAT_WITH_CONTEXT_TEMPLATE.format(
            student_name=user_context.name,
            student_id=user_context.user_id,
            cohort=user_context.cohort,
            chat_history=history_text,
            current_question=question,
        )
        full_prompt = (
            base_prompt
            + "\n\n**NGỮ CẢNH TRUY XUẤT (VECTORLESS):**\n"
            + ("\n\n".join(context_blocks) if context_blocks else "(Không tìm thấy đoạn phù hợp)")
            + "\n\nHãy trả lời dựa trên ngữ cảnh ở trên. Nếu thiếu thông tin thì nói rõ."
        )

        config = types.GenerateContentConfig(
            temperature=settings.GEMINI_TEMPERATURE,
            max_output_tokens=settings.GEMINI_MAX_OUTPUT_TOKENS,
            system_instruction=CHAT_SYSTEM_PROMPT,
        )

        all_chunks = []
        stream = await gemini_client.client.aio.models.generate_content_stream(
            model=settings.GEMINI_MODEL,
            contents=full_prompt,
            config=config,
        )

        async for chunk in stream:
            all_chunks.append(chunk)
            if hasattr(chunk, "text") and chunk.text:
                yield json.dumps({"chunk": chunk.text, "done": False})

        token_usage = {}
        for chunk in all_chunks:
            chunk_usage = extract_token_usage(chunk)
            if chunk_usage:
                token_usage = chunk_usage

        sources = await enrich_sources_with_urls(citations, self.file_repo)

        yield json.dumps(
            {
                "done": True,
                "sources": sources if sources else None,
                "token_usage": token_usage if token_usage else None,
                "processing_time_ms": int((time.time() - start_time) * 1000),
            }
        )

_chat_service_instance: Optional[ChatService] = None

def get_chat_service() -> ChatService:
    """Get singleton instance of ChatService."""
    global _chat_service_instance
    if _chat_service_instance is None:
        _chat_service_instance = ChatService()
    return _chat_service_instance

chat_service = get_chat_service()
