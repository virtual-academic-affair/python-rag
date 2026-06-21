"""Chat Service - Handles non-streaming Agentic RAG chat operations."""
import logging
import time
from typing import Optional, Any
import asyncio

from google.genai import types
from app.core.config import settings
from app.modules.chat.dtos import ChatHistoryItem, UserContext
from app.modules.chat.repositories.chat_history_repository import PERSISTED_STEP_TYPES
from app.modules.chat.utils import simplify_step
from app.modules.rag.retrieval.retrieval_service import get_retrieval_service
from app.modules.rag.agent import (
    CHAT_SYSTEM_PROMPT,
    run_agent_loop,
)
from app.modules.faq.services.faq_service import get_faq_service
from app.modules.chat.services.query_analyzer_service import get_query_analyzer
from app.utils.format_utils import markdown_to_rich_text

logger = logging.getLogger(__name__)


class ChatService:
    """Service for non-streaming Agentic RAG chat operations."""

    def __init__(self):
        self._retrieval = get_retrieval_service()
        self._faq_svc = None

    async def _get_faq_svc(self):
        if self._faq_svc is None:
            self._faq_svc = await get_faq_service()
        return self._faq_svc

    async def _embed(self, text: str) -> list[float]:
        return await self._retrieval._qdrant._get_embedding(text)

    async def _prepare_chat_state(
        self,
        question: str,
        user_context: UserContext,
        chat_history: list[ChatHistoryItem],
        metadata_filter: Optional[dict[str, Any]] = None,
    ) -> dict:
        """Retrieve candidate files and build conversation history for the agent."""
        meta_dict = metadata_filter or {}
        candidate_files = await self._retrieval.retrieve_candidate_files(
            query=question,
            metadata_filter=meta_dict,
        )

        if not candidate_files:
            return {"candidate_files": [], "history": []}

        files_info_str = "\n".join([
            f"[{i+1}] ID: {c['file_id']} | Name: {c['file_name']} | Description: {c.get('doc_description', '')}"
            for i, c in enumerate(candidate_files)
        ])
        prompt_text = (
            f"Ngữ cảnh người dùng: {user_context.name} (Vai trò: {user_context.role}, Khóa: {user_context.enrollment_year or 'N/A'})\n\n"
            f"Dưới đây là các tài liệu liên quan được tìm thấy trong cơ sở dữ liệu. Hãy sử dụng công cụ để đọc nội dung chi tiết bằng cách dùng số thứ tự [n] trong ngoặc vuông (ví dụ: '1'):\n{files_info_str}\n\n"
            f"Câu hỏi của người dùng: {question}"
        )

        # Build conversation history (latest 6 turns) + current prompt
        history = []
        for h in chat_history[-6:]:
            role = "user" if h.role == "user" else "model"
            history.append(types.Content(role=role, parts=[types.Part.from_text(text=h.content)]))
        history.append(types.Content(role="user", parts=[types.Part.from_text(text=prompt_text)]))

        return {"candidate_files": candidate_files, "history": history}

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
        Delegates fully to shared run_agent_loop; returns answer, steps, and sources.
        """
        start_time = time.time()
        pipeline_steps = []
        
        # [1] Analyze query (rewrite + gate + metadata) — 1 LLM call
        analyzer = get_query_analyzer()
        analysis = await analyzer.analyze_query(question, chat_history)
        effective_question = analysis["effective_question"]
        needs_rag = analysis["needs_rag"]
        metadata_filter = analysis.get("metadata_filter") or {}
        
        # Merge user context enrollment_year as fallback if not extracted from query
        if not metadata_filter.get("enrollment_year") and user_context.enrollment_year:
            logger.info("[Chat] Fallback enrollment_year to user context: %s", user_context.enrollment_year)
            metadata_filter["enrollment_year"] = {
                "from_year": user_context.enrollment_year,
                "to_year": user_context.enrollment_year
            }

        logger.info("[Chat] Final metadata_filter applied: %s", metadata_filter or "(none)")

        pipeline_steps.append({
            "type": "query_analysis",
            "original_question": question,
            "effective_question": effective_question,
            "needs_rag": needs_rag,
            "metadata_filter": metadata_filter,
        })

        # [2] Gate = NO: generate direct reply
        if not needs_rag:
            logger.info("[Chat] RAG bypass via gate. Generating direct answer.")
            direct_answer = await analyzer.generate_reply(effective_question, chat_history)
            processing_time_ms = int((time.time() - start_time) * 1000)
            logger.info(f"[Chat] RAG bypass. Final answer for user {user_context.name}: '{direct_answer[:200]}...' (Completed in {processing_time_ms}ms)")
            answer_markdown = direct_answer
            final_answer = answer_markdown
            if to_rich_text:
                final_answer = markdown_to_rich_text(answer_markdown)

            return {
                "answer": final_answer,
                "sources": [],
                "steps": [simplify_step(s) for s in pipeline_steps],
                "token_usage": None,
                "processing_time_ms": processing_time_ms,
            }

        # [3] Embed rewritten question
        question_vector = await self._embed(effective_question)

        # [4] FAQ Pre-check
        faq_svc = await self._get_faq_svc()
        # Omit 'type' filter from FAQ search query filter
        faq_metadata_filter = {k: v for k, v in metadata_filter.items() if k != "type"} if metadata_filter else {}
        faq = await faq_svc.find_best_match(question_vector, faq_metadata_filter)
        if faq:
            pipeline_steps.append({
                "type": "faq_check",
                "hit": True,
                "faq_question": faq.question,
            })
            processing_time_ms = int((time.time() - start_time) * 1000)
            logger.info(f"[Chat] FAQ hit: '{faq.question}' ({processing_time_ms}ms)")
            answer_markdown = faq.answer_markdown
            final_answer = answer_markdown
            if to_rich_text:
                final_answer = markdown_to_rich_text(answer_markdown)
            
            return {
                "answer": final_answer,
                "source": "faq",
                "sources": [],
                "steps": [simplify_step(s) for s in pipeline_steps],
                "token_usage": None,
                "processing_time_ms": processing_time_ms,
            }

        pipeline_steps.append({
            "type": "faq_check",
            "hit": False,
        })

        # [5] Prepare Chat State using effective_question
        state = await self._prepare_chat_state(effective_question, user_context, chat_history, metadata_filter)
        candidate_files = state["candidate_files"]

        # Log retrieval step
        retrieval_files_step = [
            {
                "file_id": f.get("file_id"),
                "file_name": f.get("file_name"),
                "doc_score": f.get("doc_score"),
            }
            for f in candidate_files
        ]
        pipeline_steps.append({
            "type": "retrieval",
            "candidate_files": retrieval_files_step,
        })

        if not candidate_files:
            answer_text = "Không tìm thấy tài liệu nào phù hợp với yêu cầu của bạn."
            if to_rich_text:
                answer_text = markdown_to_rich_text(answer_text)
            return {
                "answer": answer_text,
                "sources": [],
                "steps": [simplify_step(s, candidate_files) for s in pipeline_steps],
                "processing_time_ms": int((time.time() - start_time) * 1000),
            }

        result = await run_agent_loop(
            candidate_files=candidate_files,
            prompt_contents=state["history"],
            resolve_citations=resolve_citations,
            citation_link_type=citation_link_type,
            system_prompt=CHAT_SYSTEM_PROMPT,
        )

        processing_time_ms = int((time.time() - start_time) * 1000)
        logger.info(f"[Chat] Final answer for user {user_context.name}: '{result['final_answer'][:200]}...' (Completed in {processing_time_ms}ms)")

        # Log async interaction
        faq_svc = await self._get_faq_svc()
        asyncio.create_task(faq_svc.log_interaction(
            question=effective_question,
            question_vector=question_vector,
            answer_markdown=result["final_answer"],
            metadata_filter=metadata_filter,
            source_type="chat",
            processing_time_ms=processing_time_ms,
        ))

        answer_markdown = result["final_answer"]
        final_answer = answer_markdown
        if to_rich_text:
            final_answer = markdown_to_rich_text(answer_markdown)

        # Only persist structural pipeline steps
        agent_call_steps = [s for s in result["steps"] if s.get("type") in PERSISTED_STEP_TYPES]

        return {
            "answer": final_answer,
            "source": "llm",
            "sources": result["sources"],
            "steps": [simplify_step(s, candidate_files) for s in (pipeline_steps + agent_call_steps)],
            "token_usage": result.get("tokenUsage"),
            "processing_time_ms": processing_time_ms,
        }


_chat_service_instance: Optional[ChatService] = None


def get_chat_service() -> ChatService:
    global _chat_service_instance
    if _chat_service_instance is None:
        _chat_service_instance = ChatService()
    return _chat_service_instance
