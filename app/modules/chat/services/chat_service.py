"""Chat Service - Handles non-streaming Agentic RAG chat operations."""
import asyncio
import logging
import time
from typing import Any, Optional

from app.modules.chat.dtos import ChatHistoryItem, UserContext, TokenUsage
from app.modules.chat.repositories.chat_history_repository import PERSISTED_STEP_TYPES
from app.modules.chat.utils import simplify_step
from app.modules.faq.services.faq_service import get_faq_service
from app.modules.rag.query import RagQueryInput, get_rag_query_pipeline
from app.utils.format_utils import markdown_to_rich_text

logger = logging.getLogger(__name__)


def fire_and_forget(coro):
    task = asyncio.create_task(coro)
    task.add_done_callback(
        lambda t: logger.error("Background task failed: %s", t.exception()) if t.exception() else None
    )


class ChatService:
    """Service for non-streaming Agentic RAG chat operations."""

    def __init__(self):
        self._rag_query = get_rag_query_pipeline()
        self._faq_svc = None

    def _get_rag_query(self):
        if not hasattr(self, "_rag_query") or self._rag_query is None:
            self._rag_query = get_rag_query_pipeline()
        return self._rag_query

    async def _get_faq_svc(self):
        if self._faq_svc is None:
            self._faq_svc = await get_faq_service()
        return self._faq_svc

    async def generate_chat_response(
        self,
        question: str,
        user_context: UserContext,
        chat_history: list[ChatHistoryItem],
        resolve_citations: bool = False,
        citation_link_type: str = "markdown",
        to_rich_text: bool = False,
    ) -> dict:
        """
        Generate Agentic Chat Response (non-streaming).
        Delegates query lifecycle to the shared RAG query pipeline.
        """
        start_time = time.time()
        logger.info(f"[Chat] Nhận request từ user {user_context.name} (Role: {user_context.role}). Câu hỏi: '{question}'")

        rag_result = await self._get_rag_query().answer_chat(
            RagQueryInput(
                mode="chat",
                question=question,
                user_role=user_context.role,
                user_name=user_context.name,
                enrollment_year=user_context.enrollment_year,
                chat_history=chat_history,
                resolve_citations=resolve_citations,
                citation_link_type=citation_link_type,
            )
        )
        candidate_files = rag_result.candidate_files
        processing_time_ms = int((time.time() - start_time) * 1000)
        logger.info(f"[Chat] Pipeline completed in {processing_time_ms}ms | found={len(candidate_files)} files")

        answer_markdown = rag_result.answer_markdown
        final_answer = markdown_to_rich_text(answer_markdown) if to_rich_text else answer_markdown
        token_usage_obj = self._token_usage_obj(rag_result.token_usage)
        simplified_steps = [simplify_step(s, candidate_files) for s in rag_result.steps]
        simplified_steps = [step for step in simplified_steps if step.get("type") in PERSISTED_STEP_TYPES]

        if rag_result.is_direct_reply:
            return {
                "answer": final_answer,
                "sources": [],
                "steps": simplified_steps,
                "token_usage": token_usage_obj,
                "processing_time_ms": processing_time_ms,
            }

        logger.info(f"[Chat] Final answer for user {user_context.name}: '{answer_markdown[:200]}...' (Completed in {processing_time_ms}ms)")

        # Log async interaction if final answer was generated successfully
        if rag_result.source != "bypass" and not rag_result.max_turns_reached:
            faq_svc = await self._get_faq_svc()
            fire_and_forget(faq_svc.log_interaction(
                question=rag_result.analysis.effective_question if rag_result.analysis else question,
                answer_markdown=answer_markdown,
                metadata_filter=rag_result.analysis.metadata_filter if rag_result.analysis else {},
                source_type="chat",
                processing_time_ms=processing_time_ms,
            ))
        else:
            logger.warning(f"[Chat] Agent reached max turns for user {user_context.name}. Skipping FAQ logging.")

        return {
            "answer": final_answer,
            "source": rag_result.source,
            "sources": rag_result.sources,
            "steps": simplified_steps,
            "token_usage": token_usage_obj,
            "processing_time_ms": processing_time_ms,
        }

    @staticmethod
    def _token_usage_obj(token_usage: dict[str, Any] | None) -> TokenUsage | None:
        if not token_usage:
            return None
        return TokenUsage(
            prompt_tokens=token_usage.get("promptTokens") or token_usage.get("prompt_tokens") or 0,
            completion_tokens=token_usage.get("completionTokens") or token_usage.get("completion_tokens") or 0,
            total_tokens=token_usage.get("totalTokens") or token_usage.get("total_tokens") or 0,
        )


_chat_service_instance: Optional[ChatService] = None


def get_chat_service() -> ChatService:
    global _chat_service_instance
    if _chat_service_instance is None:
        _chat_service_instance = ChatService()
    return _chat_service_instance
