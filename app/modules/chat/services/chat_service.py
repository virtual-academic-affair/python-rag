"""Chat Service - Handles non-streaming Agentic RAG chat operations."""
import json
import logging
import time
from typing import Optional, Any
import asyncio

from google.genai import types
from app.core.config import settings
from app.integrations.llm.gemini import gemini_client
from app.utils.retry import async_retry
from app.modules.chat.dtos import ChatHistoryItem, UserContext, TokenUsage
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


def fire_and_forget(coro):
    task = asyncio.create_task(coro)
    task.add_done_callback(
        lambda t: logger.error("Background task failed: %s", t.exception()) if t.exception() else None
    )


class ChatService:
    """Service for non-streaming Agentic RAG chat operations."""

    def __init__(self):
        self._retrieval = get_retrieval_service()
        self._faq_svc = None

    async def _get_faq_svc(self):
        if self._faq_svc is None:
            self._faq_svc = await get_faq_service()
        return self._faq_svc

    async def _prepare_chat_state(
        self,
        question: str,
        user_context: UserContext,
        chat_history: list[ChatHistoryItem],
        metadata_filter: Optional[dict[str, Any]] = None,
    ) -> dict:
        """Corpus traversal: retrieve file candidates + supporting FAQ context."""
        from app.modules.corpus.services.corpus_traversal_service import get_corpus_traversal_service

        traversal_svc = get_corpus_traversal_service()
        try:
            result = await traversal_svc.traverse(question)
        except Exception as e:
            logger.warning(f"[Corpus] traverse failed (best-effort): {e}")
            from app.modules.corpus.dtos.traversal import TraversalResult
            result = TraversalResult()

        # Enrich + lọc metadata (khóa/năm học) và quyền (student không thấy lecturer_only)
        candidate_files = await self._retrieval.enrich_corpus_candidates(
            result.file_candidates,
            metadata_filter=metadata_filter,
            user_role=user_context.role,
        )

        # Fetch supporting FAQ documents (dùng cho Stage 3 fast-path và ngữ cảnh Stage 4)
        faq_docs = []
        if result.supporting_faqs:
            faq_svc = await self._get_faq_svc()
            for cand in result.supporting_faqs[:3]:
                faq = await faq_svc.get_faq(cand.leaf_id)
                if faq and faq.is_active:
                    faq_docs.append(faq)

        faq_context = ""
        if faq_docs:
            faq_parts = [
                f"**Câu hỏi liên quan:** {f.question}\n**Trả lời tham khảo:** {f.answer_markdown}"
                for f in faq_docs
            ]
            faq_context = (
                "## Ngữ cảnh bổ sung từ FAQ (tham khảo, không phải câu trả lời cuối):\n\n"
                + "\n\n---\n\n".join(faq_parts)
                + "\n\n"
            )

        if not candidate_files:
            logger.info(f"[Corpus] _prepare_chat_state: no files ({len(faq_docs)} FAQs available)")
            return {"candidate_files": [], "history": [], "faq_docs": faq_docs}

        files_info_str = "\n".join([
            f"[{i+1}] ID: {c['file_id']} | Name: {c['file_name']} | Description: {c.get('doc_description', '')}"
            for i, c in enumerate(candidate_files)
        ])

        prompt_text = (
            f"Ngữ cảnh người dùng: {user_context.name} (Vai trò: {user_context.role}, Khóa: {user_context.enrollment_year or 'N/A'})\n\n"
            f"{faq_context}"
            "Dưới đây là các tài liệu liên quan được tìm thấy trong cơ sở dữ liệu. Hãy sử dụng công cụ để đọc nội dung chi tiết bằng cách dùng số thứ tự [n] trong ngoặc vuông (ví dụ: '1'):\n"
            f"{files_info_str}\n\n"
            f"Câu hỏi của người dùng: {question}"
        )

        history = []
        for h in chat_history[-6:]:
            role = "user" if h.role == "user" else "model"
            history.append(types.Content(role=role, parts=[types.Part.from_text(text=h.content)]))
        history.append(types.Content(role="user", parts=[types.Part.from_text(text=prompt_text)]))

        return {"candidate_files": candidate_files, "history": history, "faq_docs": faq_docs}

    async def _try_faq_fast_path(self, question: str, faq_docs: list) -> Optional[str]:
        """
        Stage 3 — Fast-Path Resolution: ưu tiên trả lời từ FAQ.
        Trả về câu trả lời markdown nếu FAQ đủ thông tin, ngược lại None (→ Stage 4).
        Best-effort: mọi lỗi LLM đều fallback về None.
        """
        if not faq_docs:
            return None

        faq_block = "\n\n---\n\n".join(
            f"Câu hỏi: {f.question}\nTrả lời: {f.answer_markdown}" for f in faq_docs
        )
        prompt = (
            "Bạn là trợ lý giáo vụ đại học. Dưới đây là các cặp câu hỏi - trả lời (FAQ) đã kiểm duyệt.\n\n"
            f"FAQ:\n{faq_block}\n\n"
            f'Câu hỏi của người dùng: "{question}"\n\n'
            "Nếu các FAQ trên ĐỦ thông tin để trả lời đầy đủ và chính xác câu hỏi, "
            "hãy trả lời dựa HOÀN TOÀN trên nội dung FAQ (định dạng markdown).\n"
            "Nếu KHÔNG đủ (câu hỏi cần chi tiết hơn, khác ngữ cảnh, hoặc FAQ không liên quan), "
            "đánh dấu sufficient=false.\n\n"
            'Trả về JSON: {"sufficient": true/false, "answer": "câu trả lời markdown hoặc chuỗi rỗng"}'
        )
        try:
            resp = await async_retry(
                gemini_client.client.aio.models.generate_content,
                model=settings.FAQ_MATCHER_MODEL or settings.GEMINI_MODEL,
                contents=[prompt],
                config=types.GenerateContentConfig(
                    temperature=0.0,
                    response_mime_type="application/json",
                ),
            )
            data = json.loads(resp.text or "{}")
        except Exception as e:
            logger.warning(f"[Chat] FAQ fast-path failed (best-effort): {e}")
            return None

        if data.get("sufficient") and data.get("answer"):
            logger.info("[Chat] FAQ fast-path: sufficient — answering from FAQ")
            return data["answer"]
        logger.info("[Chat] FAQ fast-path: insufficient — proceeding to document reading")
        return None

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
        logger.info(f"[Chat] Nhận request từ user {user_context.name} (Role: {user_context.role}). Câu hỏi: '{question}'")

        # [1] Analyze query (rewrite + gate + metadata) — 1 LLM call
        analyzer = get_query_analyzer()
        start_analysis = time.perf_counter()
        analysis = await analyzer.analyze_query(question, chat_history)
        logger.info(f"[Chat] QueryAnalysis done in {time.perf_counter() - start_analysis:.2f}s")
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
            direct_answer, reply_usage = await analyzer.generate_reply(effective_question, chat_history)
            processing_time_ms = int((time.time() - start_time) * 1000)
            logger.info(f"[Chat] RAG bypass. Final answer for user {user_context.name}: '{direct_answer[:200]}...' (Completed in {processing_time_ms}ms)")
            answer_markdown = direct_answer
            final_answer = answer_markdown
            if to_rich_text:
                final_answer = markdown_to_rich_text(answer_markdown)

            analysis_usage = analysis.get("usage")
            total_prompt_tokens = 0
            total_candidates_tokens = 0
            if analysis_usage:
                total_prompt_tokens += analysis_usage.get("prompt_tokens", 0)
                total_candidates_tokens += analysis_usage.get("completion_tokens", 0)
            if reply_usage:
                total_prompt_tokens += reply_usage.get("prompt_tokens", 0)
                total_candidates_tokens += reply_usage.get("completion_tokens", 0)

            token_usage_obj = None
            if analysis_usage or reply_usage:
                token_usage_obj = TokenUsage(
                    prompt_tokens=total_prompt_tokens,
                    completion_tokens=total_candidates_tokens,
                    total_tokens=total_prompt_tokens + total_candidates_tokens
                )

            return {
                "answer": final_answer,
                "sources": [],
                "steps": [simplify_step(s) for s in pipeline_steps],
                "token_usage": token_usage_obj,
                "processing_time_ms": processing_time_ms,
            }

        # [3] Prepare Chat State using effective_question (corpus traversal)
        start_retrieval = time.perf_counter()
        state = await self._prepare_chat_state(effective_question, user_context, chat_history, metadata_filter)
        candidate_files = state["candidate_files"]
        logger.info(
            f"[Chat] Retrieval done in {time.perf_counter() - start_retrieval:.2f}s | "
            f"found={len(candidate_files)} files"
        )

        # Log retrieval step
        retrieval_files_step = [
            {
                "file_id": f.get("file_id"),
                "file_name": f.get("file_name"),
            }
            for f in candidate_files
        ]
        pipeline_steps.append({
            "type": "retrieval",
            "candidate_files": retrieval_files_step,
        })

        # [4] Stage 3 — Fast-Path Resolution: ưu tiên trả lời từ FAQ
        start_faq = time.perf_counter()
        faq_answer = await self._try_faq_fast_path(effective_question, state.get("faq_docs") or [])
        logger.info(f"[Chat] FAQ fast-path check done in {time.perf_counter() - start_faq:.2f}s")
        if faq_answer:
            pipeline_steps.append({"type": "faq_check", "matched": True})
            processing_time_ms = int((time.time() - start_time) * 1000)
            logger.info(f"[Chat] FAQ fast-path answer for user {user_context.name}: '{faq_answer[:200]}...' ({processing_time_ms}ms)")
            final_answer = faq_answer
            if to_rich_text:
                final_answer = markdown_to_rich_text(faq_answer)
            return {
                "answer": final_answer,
                "source": "faq",
                "sources": [],
                "steps": [simplify_step(s, candidate_files) for s in pipeline_steps],
                "processing_time_ms": processing_time_ms,
            }

        # [5] Stage 4 — Page Index: đọc tài liệu qua agent loop
        if not candidate_files:
            logger.info(f"[Chat] No candidate files and no FAQ match for user {user_context.name}. Returning empty result.")
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
        
        answer_markdown = result["final_answer"]
        if not answer_markdown:
            logger.warning(f"[Chat] Empty answer from agent loop for user {user_context.name}. Using fallback.")
            answer_markdown = "Hệ thống chưa tổng hợp được câu trả lời từ tài liệu. Vui lòng hỏi lại cụ thể hơn."

        logger.info(f"[Chat] Final answer for user {user_context.name}: '{answer_markdown[:200]}...' (Completed in {processing_time_ms}ms)")

        # Log async interaction if final answer was generated successfully
        if not result.get("max_turns_reached"):
            faq_svc = await self._get_faq_svc()
            fire_and_forget(faq_svc.log_interaction(
                question=effective_question,
                answer_markdown=answer_markdown,
                metadata_filter=metadata_filter,
                source_type="chat",
                processing_time_ms=processing_time_ms,
            ))
        else:
            logger.warning(f"[Chat] Agent reached max turns for user {user_context.name}. Skipping FAQ logging.")

        final_answer = answer_markdown
        if to_rich_text:
            final_answer = markdown_to_rich_text(answer_markdown)

        # Only persist structural pipeline steps
        agent_call_steps = [s for s in result["steps"] if s.get("type") in PERSISTED_STEP_TYPES]

        agent_usage = result.get("tokenUsage")
        token_usage_obj = None
        if agent_usage:
            token_usage_obj = TokenUsage(
                prompt_tokens=agent_usage.get("promptTokens") or agent_usage.get("prompt_tokens") or 0,
                completion_tokens=agent_usage.get("completionTokens") or agent_usage.get("completion_tokens") or 0,
                total_tokens=agent_usage.get("totalTokens") or agent_usage.get("total_tokens") or 0
            )

        return {
            "answer": final_answer,
            "source": "llm",
            "sources": result["sources"],
            "steps": [simplify_step(s, candidate_files) for s in (pipeline_steps + agent_call_steps)],
            "token_usage": token_usage_obj,
            "processing_time_ms": processing_time_ms,
        }


_chat_service_instance: Optional[ChatService] = None


def get_chat_service() -> ChatService:
    global _chat_service_instance
    if _chat_service_instance is None:
        _chat_service_instance = ChatService()
    return _chat_service_instance
