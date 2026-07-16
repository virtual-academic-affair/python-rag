"""Chat Stream Service - Handles streaming Agentic RAG chat operations."""
import json
import logging
import time
from typing import Optional, AsyncGenerator

from app.modules.chat.dtos import ChatHistoryItem, UserContext, TokenUsage
from app.modules.chat.repositories.chat_history_repository import PERSISTED_STEP_TYPES
from app.modules.chat.utils import simplify_step
from app.modules.rag.query.dtos import SourceCitation
from app.modules.rag.query import RagQueryInput
from app.modules.chat.services.chat_service import ChatService, fire_and_forget

logger = logging.getLogger(__name__)


class ChatStreamService(ChatService):
    """Service for streaming Agentic RAG chat operations."""

    async def stream_chat_response(
        self,
        question: str,
        user_context: UserContext,
        chat_history: list[ChatHistoryItem],
    ) -> AsyncGenerator[str, None]:
        """
        Stream chat response via SSE.
        """
        start_time = time.time()
        pipeline_steps = []
        candidate_files = []
        agent_result = None
        analysis = None
        logger.info(f"[Chat-Stream] Nhận request từ user {user_context.name} (Role: {user_context.role}). Câu hỏi: '{question}'")

        async for event in self._get_rag_query().stream_chat(
            RagQueryInput(
                mode="chat",
                question=question,
                user_role=user_context.role,
                user_name=user_context.name,
                enrollment_year=user_context.enrollment_year,
                chat_history=chat_history,
            )
        ):
            if event.get("type") == "_query_analysis_start":
                yield json.dumps({"type": "query_analysis", "content": event.get("content", ""), "done": False})
                continue
            if event.get("type") == "_query_analysis":
                step = event.get("step") or {}
                analysis = event.get("analysis") or step
                pipeline_steps.append(step)
                yield json.dumps({**simplify_step(step), "done": False})
                continue
            if event.get("type") == "_corpus_tree":
                step = {
                    "type": "corpus_tree",
                    "content": event.get("content") or "Đã tải cây chủ đề phù hợp.",
                    "tree": event.get("tree") or [],
                }
                pipeline_steps.append(step)
                yield json.dumps({**simplify_step(step), "done": False})
                continue
            if event.get("type") == "_corpus_traversal":
                step = event.get("step") or {}
                pipeline_steps.append(step)
                yield json.dumps({**simplify_step(step, candidate_files), "done": False})
                continue
            if event.get("type") == "_pipeline_step":
                candidate_files = event.get("candidate_files") or []
                step = event.get("step") or {}
                pipeline_steps.append(step)
                yield json.dumps({**simplify_step(step, candidate_files), "done": False})
                continue
            if event.get("type") == "_pipeline_result":
                answer_text = event.get("answer_markdown") or "Không tìm thấy tài liệu phù hợp."
                yield json.dumps({"type": "text", "content": answer_text, "done": False})
                token_usage_obj = self._token_usage_obj(event.get("token_usage"))
                processing_time_ms = int((time.time() - start_time) * 1000)
                if event.get("source") == "faq":
                    faq_svc = await self._get_faq_svc()
                    fire_and_forget(faq_svc.log_interaction(
                        question=self._effective_question_from_steps(event.get("steps") or pipeline_steps, question),
                        answer_markdown=answer_text,
                        metadata_filter=self._metadata_filter_from_steps(event.get("steps") or pipeline_steps),
                        source_type="chat",
                        processing_time_ms=processing_time_ms,
                    ))
                faq_recommendation = self._build_faq_recommendation(
                    analysis=event.get("analysis") or analysis,
                    sources=event.get("sources") or [],
                    candidate_files=event.get("candidate_files") or candidate_files,
                    used_faq_docs=event.get("used_faq_docs") or [],
                )
                yield json.dumps({
                    "done": True,
                    "source": event.get("source", "llm"),
                    "sources": [SourceCitation(**s).model_dump(by_alias=True) for s in event.get("sources", [])] if event.get("sources") else [],
                    "steps": [simplify_step(s, candidate_files) for s in (event.get("steps") or pipeline_steps)],
                    "tokenUsage": token_usage_obj.model_dump(by_alias=True) if token_usage_obj else None,
                    "processingTimeMs": processing_time_ms,
                    "faqRecommendation": faq_recommendation.model_dump(by_alias=True) if faq_recommendation else None,
                })
                return
            if event.get("type") == "_agent_result":
                agent_result = event
                continue
            if event.get("type") == "call" and event.get("step"):
                yield json.dumps({**simplify_step(event["step"], candidate_files), "done": False})
                continue
            yield json.dumps(event)

        if agent_result is None:
            agent_result = {
                "final_answer": "Hệ thống chưa tổng hợp được câu trả lời từ tài liệu. Vui lòng hỏi lại cụ thể hơn.",
                "max_turns_reached": False,
                "steps": [],
                "sources": [],
                "token_usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            }

        final_answer_accumulated = agent_result["final_answer"]
        max_turns_reached = agent_result["max_turns_reached"]
        processing_time_ms = int((time.time() - start_time) * 1000)
        
        if not max_turns_reached:
            faq_svc = await self._get_faq_svc()
            fire_and_forget(faq_svc.log_interaction(
                question=self._effective_question_from_steps(pipeline_steps, question),
                answer_markdown=final_answer_accumulated,
                metadata_filter=self._metadata_filter_from_steps(pipeline_steps),
                source_type="chat",
                processing_time_ms=processing_time_ms,
            ))
        else:
            logger.warning(f"[Chat-Stream] Agent reached max turns for user {user_context.name}. Skipping FAQ logging.")
            
        stream_steps = agent_result["steps"]
        simplified_stream_steps = [simplify_step(step, candidate_files) for step in stream_steps]
        filtered_stream_steps = [
            step for step in simplified_stream_steps if step.get("type") in PERSISTED_STEP_TYPES
        ]
        token_usage = agent_result["token_usage"]

        token_usage_obj = TokenUsage(
            prompt_tokens=token_usage.get("prompt_tokens", 0),
            completion_tokens=token_usage.get("completion_tokens", 0),
            total_tokens=token_usage.get("total_tokens", 0)
        )
        faq_recommendation = self._build_faq_recommendation(
            analysis=analysis,
            sources=agent_result["sources"],
            candidate_files=candidate_files,
            used_faq_docs=[],
        )

        yield json.dumps({
            "done": True,
            "source": "llm",
            "sources": [SourceCitation(**s).model_dump(by_alias=True) for s in agent_result["sources"]] if agent_result["sources"] else [],
            "steps": [simplify_step(s, candidate_files) for s in pipeline_steps] + filtered_stream_steps,
            "tokenUsage": token_usage_obj.model_dump(by_alias=True),
            "processingTimeMs": processing_time_ms,
            "faqRecommendation": faq_recommendation.model_dump(by_alias=True) if faq_recommendation else None,
        })

    @staticmethod
    def _effective_question_from_steps(steps: list[dict], fallback: str) -> str:
        for step in steps:
            if step.get("type") == "query_analysis":
                return step.get("effective_question") or fallback
        return fallback

    @staticmethod
    def _metadata_filter_from_steps(steps: list[dict]) -> dict:
        for step in steps:
            if step.get("type") == "query_analysis":
                return step.get("metadata_filter") or {}
        return {}


_chat_stream_service_instance: Optional[ChatStreamService] = None


def get_chat_stream_service() -> ChatStreamService:
    global _chat_stream_service_instance
    if _chat_stream_service_instance is None:
        _chat_stream_service_instance = ChatStreamService()
    return _chat_stream_service_instance
