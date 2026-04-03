"""
Chat Service - Handles RAG-based chat operations (generate/stream).
"""
import json
import time
from typing import Optional, AsyncGenerator, Any

from google.genai import types

from app.core.config import settings
from app.core.prompts import (
    CHAT_SYSTEM_PROMPT,
    CHAT_WITH_CONTEXT_TEMPLATE,
)
from app.models.schemas import ChatHistoryItem, UserContext
from app.repositories.file_repository import FileRepository
from app.services.rag.gemini_client import gemini_client
from app.services.rag.graphiti.graphiti_retrieval_service import graphiti_retrieval_service
from app.services.rag.utils.gemini_rag_utils import (
    format_chat_history,
    enrich_sources_with_urls,
    extract_token_usage,
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
        metadata_filter: Optional[dict[str, Any]] = None,
    ) -> dict:
        """Generate chat response using Graphiti retrieval + Gemini generation."""
        if not store_name:
            raise ValueError("store_name is required for GraphRAG retrieval.")

        start_time = time.time()
        history_text = format_chat_history(chat_history)

        chunks = await graphiti_retrieval_service.retrieve_chunks(
            question=question,
            store_id=store_name,
            metadata_filter=metadata_filter or {},
            top_k=8,
        )

        context_text = self._build_context_text(chunks)
        prompt_with_context = (
            f"{CHAT_WITH_CONTEXT_TEMPLATE.format(student_name=user_context.name, student_id=user_context.user_id, cohort=user_context.cohort, chat_history=history_text, current_question=question)}\n\n"
            f"=== NGỮ CẢNH TRUY XUẤT TỪ KHO TRI THỨC ===\n{context_text}\n"
            "=== HƯỚNG DẪN TRÍCH DẪN ===\n"
            "Khi dùng thông tin từ ngữ cảnh, ghi chú nguồn dạng [^id] theo citation_id."
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
            contents=prompt_with_context,
            config=config,
        )

        processing_time_ms = int((time.time() - start_time) * 1000)
        answer = response.text if hasattr(response, "text") else ""
        sources = self._build_sources_from_chunks(chunks)
        sources = await enrich_sources_with_urls(sources, self.file_repo)
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
        metadata_filter: Optional[dict[str, Any]] = None,
    ) -> AsyncGenerator[str, None]:
        """Stream chat response with Graphiti retrieval + Gemini generation."""
        result = await self.generate_chat_response(
            question=question,
            user_context=user_context,
            chat_history=chat_history,
            store_name=store_name,
            metadata_filter=metadata_filter,
        )

        answer = result.get("answer") or ""
        chunk_size = 180
        for i in range(0, len(answer), chunk_size):
            yield json.dumps({"chunk": answer[i : i + chunk_size], "done": False})

        yield json.dumps(
            {
                "done": True,
                "sources": result.get("sources"),
                "token_usage": result.get("token_usage"),
                "processing_time_ms": result.get("processing_time_ms"),
            }
        )


    @staticmethod
    def _build_context_text(chunks: list[dict[str, Any]]) -> str:
        if not chunks:
            return "Không tìm thấy ngữ cảnh phù hợp trong kho tài liệu."

        lines: list[str] = []
        for idx, c in enumerate(chunks, start=1):
            title = c.get("title") or "Tài liệu không rõ tên"
            section = c.get("section_path") or "(không rõ mục)"
            text = (c.get("text") or "").strip()
            lines.append(f"[Nguồn {idx}] {title} | {section}\n{text}")
        return "\n\n".join(lines)

    @staticmethod
    def _build_sources_from_chunks(chunks: list[dict[str, Any]]) -> Optional[list[dict[str, Any]]]:
        if not chunks:
            return None

        sources: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        citation_id = 1

        for c in chunks:
            key = (str(c.get("doc_id") or ""), str(c.get("chunk_id") or ""))
            if key in seen:
                continue
            seen.add(key)

            sources.append(
                {
                    "citation_id": citation_id,
                    "title": c.get("title"),
                    "text": c.get("text"),
                }
            )
            citation_id += 1

        return sources or None

_chat_service_instance: Optional[ChatService] = None

def get_chat_service() -> ChatService:
    """Get singleton instance of ChatService."""
    global _chat_service_instance
    if _chat_service_instance is None:
        _chat_service_instance = ChatService()
    return _chat_service_instance

chat_service = get_chat_service()
