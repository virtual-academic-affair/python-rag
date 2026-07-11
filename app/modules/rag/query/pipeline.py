from __future__ import annotations

from dataclasses import dataclass
from typing import Any, AsyncGenerator

from app.modules.rag.query.answering.pageindex import (
    CHAT_SYSTEM_PROMPT,
    EMAIL_SYSTEM_PROMPT,
    run_agent_loop,
    stream_agent_loop,
)
from app.modules.rag.query.contracts import (
    RagQueryAnalysis,
    RagQueryBehavior,
    RagQueryInput,
    RagQueryResult,
)
from app.modules.rag.query.prompts import build_chat_prompt_contents, build_email_prompt_text
from app.modules.rag.query.retrieval.retrieval_service import get_retrieval_service


CHAT_BEHAVIOR = RagQueryBehavior(
    mode="chat",
    run_chat_analyzer=True,
    allow_direct_reply=True,
    allow_enrollment_fallback=True,
    include_reasoning=True,
    system_prompt=CHAT_SYSTEM_PROMPT,
    no_candidate_message="Không tìm thấy tài liệu nào phù hợp với yêu cầu của bạn.",
)

CHAT_STREAM_BEHAVIOR = RagQueryBehavior(
    mode="chat",
    run_chat_analyzer=True,
    allow_direct_reply=True,
    allow_enrollment_fallback=True,
    include_reasoning=True,
    system_prompt=CHAT_SYSTEM_PROMPT,
    no_candidate_message="Không tìm thấy tài liệu nào phù hợp với yêu cầu của bạn.",
)

EMAIL_BEHAVIOR = RagQueryBehavior(
    mode="email",
    run_chat_analyzer=False,
    allow_direct_reply=False,
    allow_enrollment_fallback=False,
    include_reasoning=False,
    system_prompt=EMAIL_SYSTEM_PROMPT,
    no_candidate_message="Không tìm thấy tài liệu phù hợp để trả lời email này.",
    resolve_citations=True,
    citation_link_type="original",
)


@dataclass
class RagPreparedContext:
    candidate_files: list[dict[str, Any]]
    faq_docs: list[Any]
    prompt_contents: Any
    system_prompt: str


class RagQueryPipeline:
    """Shared query orchestration for chat, streaming chat, and email inquiry."""

    def __init__(self):
        self._retrieval = get_retrieval_service()
        self._analyzer = None
        self._faq_answer_service = None

    @property
    def analyzer(self):
        if self._analyzer is None:
            from app.modules.rag.query.analyzer import get_chat_query_analyzer

            self._analyzer = get_chat_query_analyzer()
        return self._analyzer

    def _get_faq_answer_service(self):
        if self._faq_answer_service is None:
            from app.modules.rag.query.answering.faq_answering import get_faq_answer_service

            self._faq_answer_service = get_faq_answer_service()
        return self._faq_answer_service

    async def answer_chat(self, query_input: RagQueryInput) -> RagQueryResult:
        return await self._run(query_input, self._with_request_citations(CHAT_BEHAVIOR, query_input))

    async def stream_chat(self, query_input: RagQueryInput) -> AsyncGenerator[dict[str, Any], None]:
        async for event in self._run_stream(
            query_input,
            self._with_request_citations(CHAT_STREAM_BEHAVIOR, query_input),
        ):
            yield event

    async def answer_email(self, query_input: RagQueryInput) -> RagQueryResult:
        return await self._run(query_input, EMAIL_BEHAVIOR)

    async def _run(self, query_input: RagQueryInput, behavior: RagQueryBehavior) -> RagQueryResult:
        analysis = await self._analyze(query_input, behavior)
        steps = [analysis.as_step()]

        if not analysis.needs_rag and behavior.allow_direct_reply:
            answer, reply_usage = await self.analyzer.generate_reply(
                analysis.effective_question,
                query_input.chat_history,
            )
            return RagQueryResult(
                answer_markdown=answer,
                source="llm",
                sources=[],
                steps=steps,
                token_usage=self._combine_direct_usage(analysis.usage, reply_usage),
                candidate_files=[],
                faq_docs=[],
                analysis=analysis,
                is_direct_reply=True,
            )

        prepared = await self._prepare_context(query_input, behavior, analysis)
        retrieval_step = self._retrieval_step(prepared.candidate_files)
        steps.append(retrieval_step)

        faq_answer = await self._try_answer_from_faqs(analysis, prepared.faq_docs)
        if faq_answer:
            faq_step = faq_answer.as_step()
            steps.append(faq_step)
            return RagQueryResult(
                answer_markdown=faq_answer.answer_markdown,
                source="faq",
                sources=[],
                steps=steps,
                token_usage=faq_answer.token_usage,
                candidate_files=prepared.candidate_files,
                faq_docs=prepared.faq_docs,
                analysis=analysis,
            )

        if not prepared.candidate_files:
            return RagQueryResult(
                answer_markdown=behavior.no_candidate_message,
                source="bypass",
                sources=[],
                steps=steps,
                token_usage=None,
                candidate_files=[],
                faq_docs=prepared.faq_docs,
                analysis=analysis,
            )

        agent_result = await run_agent_loop(
            candidate_files=prepared.candidate_files,
            prompt_contents=prepared.prompt_contents,
            resolve_citations=behavior.resolve_citations,
            citation_link_type=behavior.citation_link_type,
            system_prompt=prepared.system_prompt,
            include_reasoning=behavior.include_reasoning,
        )
        agent_steps = agent_result.get("steps") or []
        return RagQueryResult(
            answer_markdown=(
                agent_result.get("final_answer")
                or "Hệ thống chưa tổng hợp được câu trả lời từ tài liệu. Vui lòng hỏi lại cụ thể hơn."
            ),
            source="llm",
            sources=agent_result.get("sources") or [],
            steps=steps + agent_steps,
            token_usage=agent_result.get("tokenUsage"),
            candidate_files=prepared.candidate_files,
            faq_docs=prepared.faq_docs,
            max_turns_reached=bool(agent_result.get("max_turns_reached")),
            analysis=analysis,
        )

    async def _run_stream(
        self,
        query_input: RagQueryInput,
        behavior: RagQueryBehavior,
    ) -> AsyncGenerator[dict[str, Any], None]:
        yield {"type": "_query_analysis_start", "content": "Phân tích câu hỏi của người dùng..."}
        analysis = await self._analyze(query_input, behavior)
        steps = [analysis.as_step()]
        yield {"type": "_query_analysis", "analysis": analysis, "step": steps[0]}

        if not analysis.needs_rag and behavior.allow_direct_reply:
            answer, reply_usage = await self.analyzer.generate_reply(
                analysis.effective_question,
                query_input.chat_history,
            )
            yield {
                "type": "_pipeline_result",
                "answer_markdown": answer,
                "source": "llm",
                "sources": [],
                "steps": steps,
                "token_usage": self._combine_direct_usage(analysis.usage, reply_usage),
                "candidate_files": [],
                "faq_docs": [],
                "max_turns_reached": False,
                "analysis": analysis,
                "is_direct_reply": True,
            }
            return

        yield {"type": "_retrieval_start", "content": "Tìm kiếm tài liệu và câu hỏi liên quan..."}
        prepared = await self._prepare_context(query_input, behavior, analysis)
        retrieval_step = self._retrieval_step(prepared.candidate_files)
        steps.append(retrieval_step)
        yield {
            "type": "_retrieval",
            "step": retrieval_step,
            "candidate_files": prepared.candidate_files,
            "faq_docs": prepared.faq_docs,
        }

        faq_answer = await self._try_answer_from_faqs(analysis, prepared.faq_docs)
        if faq_answer:
            faq_step = faq_answer.as_step()
            steps.append(faq_step)
            yield {
                "type": "_pipeline_result",
                "answer_markdown": faq_answer.answer_markdown,
                "source": "faq",
                "sources": [],
                "steps": steps,
                "token_usage": faq_answer.token_usage,
                "candidate_files": prepared.candidate_files,
                "faq_docs": prepared.faq_docs,
                "max_turns_reached": False,
                "analysis": analysis,
                "is_direct_reply": False,
            }
            return

        if not prepared.candidate_files:
            yield {
                "type": "_pipeline_result",
                "answer_markdown": behavior.no_candidate_message,
                "source": "bypass",
                "sources": [],
                "steps": steps,
                "token_usage": None,
                "candidate_files": [],
                "faq_docs": prepared.faq_docs,
                "max_turns_reached": False,
                "analysis": analysis,
                "is_direct_reply": False,
            }
            return

        async for event in stream_agent_loop(
            candidate_files=prepared.candidate_files,
            prompt_contents=prepared.prompt_contents,
            resolve_citations=behavior.resolve_citations,
            citation_link_type=behavior.citation_link_type,
            system_prompt=prepared.system_prompt,
            include_reasoning=behavior.include_reasoning,
        ):
            yield event

    async def _analyze(self, query_input: RagQueryInput, behavior: RagQueryBehavior) -> RagQueryAnalysis:
        if behavior.run_chat_analyzer:
            raw_analysis = await self.analyzer.analyze_query(
                query_input.question,
                query_input.chat_history,
            )
            metadata_filter = raw_analysis.get("metadata_filter") or {}
            if (
                behavior.allow_enrollment_fallback
                and not metadata_filter.get("enrollment_year")
                and query_input.enrollment_year
            ):
                metadata_filter["enrollment_year"] = {
                    "from_year": query_input.enrollment_year,
                    "to_year": query_input.enrollment_year,
                }
            return RagQueryAnalysis(
                original_question=query_input.question,
                effective_question=raw_analysis.get("effective_question") or query_input.question,
                needs_rag=bool(raw_analysis.get("needs_rag", True)),
                metadata_filter=metadata_filter,
                usage=raw_analysis.get("usage"),
            )

        metadata_filter = dict(query_input.metadata_filter or {})
        if (
            behavior.allow_enrollment_fallback
            and not metadata_filter.get("enrollment_year")
            and query_input.enrollment_year
        ):
            metadata_filter["enrollment_year"] = {
                "from_year": query_input.enrollment_year,
                "to_year": query_input.enrollment_year,
            }
        return RagQueryAnalysis(
            original_question=query_input.question,
            effective_question=query_input.question,
            needs_rag=True,
            metadata_filter=metadata_filter,
        )

    async def _prepare_context(
        self,
        query_input: RagQueryInput,
        behavior: RagQueryBehavior,
        analysis: RagQueryAnalysis,
    ) -> RagPreparedContext:
        retrieval_context = await self._retrieval.retrieve_context(
            question=analysis.effective_question,
            metadata_filter=analysis.metadata_filter,
            user_role=query_input.user_role,
            max_files=query_input.max_files,
        )
        candidate_files = retrieval_context.candidate_files
        faq_docs = retrieval_context.faq_docs

        if behavior.mode == "email":
            prompt_contents = build_email_prompt_text(
                question=analysis.effective_question,
                subject=query_input.email_subject or "",
                content=query_input.email_content or "",
                metadata_filter=analysis.metadata_filter,
                candidate_files=candidate_files,
                faq_docs=faq_docs,
            )
        else:
            prompt_contents = build_chat_prompt_contents(
                question=analysis.effective_question,
                user_name=query_input.user_name,
                user_role=query_input.user_role,
                enrollment_year=query_input.enrollment_year,
                chat_history=query_input.chat_history,
                candidate_files=candidate_files,
                faq_docs=faq_docs,
            )

        return RagPreparedContext(
            candidate_files=candidate_files,
            faq_docs=faq_docs,
            prompt_contents=prompt_contents,
            system_prompt=behavior.system_prompt,
        )

    async def _try_answer_from_faqs(
        self,
        analysis: RagQueryAnalysis,
        faq_docs: list[Any],
    ) -> Any | None:
        if not faq_docs:
            return None

        return await self._get_faq_answer_service().answer(
            analysis.effective_question,
            faq_docs,
        )

    @staticmethod
    def _retrieval_step(candidate_files: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "type": "retrieval",
            "candidate_files": [
                {
                    "file_id": f.get("file_id"),
                    "file_name": f.get("file_name"),
                }
                for f in candidate_files
            ],
        }

    @staticmethod
    def _with_request_citations(
        behavior: RagQueryBehavior,
        query_input: RagQueryInput,
    ) -> RagQueryBehavior:
        return RagQueryBehavior(
            mode=behavior.mode,
            run_chat_analyzer=behavior.run_chat_analyzer,
            allow_direct_reply=behavior.allow_direct_reply,
            allow_enrollment_fallback=behavior.allow_enrollment_fallback,
            include_reasoning=behavior.include_reasoning,
            system_prompt=behavior.system_prompt,
            no_candidate_message=behavior.no_candidate_message,
            resolve_citations=query_input.resolve_citations,
            citation_link_type=query_input.citation_link_type,
        )

    @staticmethod
    def _combine_direct_usage(
        analysis_usage: dict[str, Any] | None,
        reply_usage: dict[str, Any] | None,
    ) -> dict[str, int] | None:
        if not analysis_usage and not reply_usage:
            return None
        prompt_tokens = 0
        completion_tokens = 0
        if analysis_usage:
            prompt_tokens += analysis_usage.get("prompt_tokens", 0)
            completion_tokens += analysis_usage.get("completion_tokens", 0)
        if reply_usage:
            prompt_tokens += reply_usage.get("prompt_tokens", 0)
            completion_tokens += reply_usage.get("completion_tokens", 0)
        return {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        }


_rag_query_pipeline_instance: RagQueryPipeline | None = None


def get_rag_query_pipeline() -> RagQueryPipeline:
    global _rag_query_pipeline_instance
    if _rag_query_pipeline_instance is None:
        _rag_query_pipeline_instance = RagQueryPipeline()
    return _rag_query_pipeline_instance
