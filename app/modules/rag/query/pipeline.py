from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass
import logging
import time
from typing import Any, AsyncGenerator
from uuid import uuid4

from app.modules.rag.query.answering.pageindex_agent import (
    run_pageindex_agent_loop,
    stream_pageindex_agent_loop,
)
from app.modules.rag.query.answering.pageindex_agent.prompt_builder import (
    build_chat_prompt_contents,
    build_email_prompt_text,
)
from app.modules.rag.query.behaviors import CHAT_BEHAVIOR, CHAT_STREAM_BEHAVIOR, EMAIL_BEHAVIOR
from app.modules.rag.query.contracts import (
    RagQueryAnalysis,
    RagQueryBehavior,
    RagQueryInput,
    RagQueryResult,
)
from app.modules.rag.query.retrieval.retrieval_service import RetrievalSeeds, get_retrieval_service

logger = logging.getLogger(__name__)


@dataclass
class RagPreparedContext:
    candidate_files: list[dict[str, Any]]
    prompt_contents: Any
    system_prompt: str


class RagQueryPipeline:
    """Shared query orchestration for chat, streaming chat, and email inquiry."""

    def __init__(self):
        self._retrieval = get_retrieval_service()
        self._analyzer = None
        self._email_analyzer = None
        self._faq_answer_service = None

    @property
    def analyzer(self):
        if self._analyzer is None:
            from app.modules.rag.query.analyzer import get_chat_query_analyzer

            self._analyzer = get_chat_query_analyzer()
        return self._analyzer

    @property
    def email_analyzer(self):
        if self._email_analyzer is None:
            from app.modules.rag.query.analyzer import get_email_query_analyzer

            self._email_analyzer = get_email_query_analyzer()
        return self._email_analyzer

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
        trace_id = uuid4().hex[:12]
        started_at = time.perf_counter()
        logger.info(
            "[RAG][%s][pipeline.start] mode=%s role=%s history=%d question_len=%d",
            trace_id,
            behavior.mode,
            query_input.user_role,
            len(query_input.chat_history),
            len(query_input.question),
        )
        analysis = await self._analyze(query_input, behavior)
        logger.info(
            "[RAG][%s][analysis] needs_rag=%s effective_question=%r metadata=%s inquiry_types=%s",
            trace_id,
            analysis.needs_rag,
            analysis.effective_question[:300],
            analysis.metadata_filter,
            analysis.inquiry_types,
        )
        steps = [analysis.as_step()]

        if not analysis.needs_rag and behavior.allow_direct_reply:
            answer, reply_usage = await self.analyzer.generate_reply(
                analysis.effective_question,
                query_input.chat_history,
            )
            result = RagQueryResult(
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
            logger.info("[RAG][%s][pipeline.complete] source=direct_llm duration_ms=%d", trace_id, int((time.perf_counter() - started_at) * 1000))
            return result

        seeds = await self._retrieval.traverse_query(
            question=analysis.effective_question,
            metadata_filter=analysis.metadata_filter,
            user_role=query_input.user_role,
            trace_id=trace_id,
        )
        steps.extend(seeds.traversal_steps)
        faq_docs: list[Any] = []
        faq_answer = None
        if seeds.faq_candidates:
            faq_docs = await self._prepare_faq_context(analysis, seeds, trace_id=trace_id)
            steps.append(self._build_faq_retrieval_step(seeds, faq_docs))
            faq_answer = await self._try_answer_from_faqs(analysis, faq_docs)
            if faq_docs:
                steps.append(self._build_faq_answer_step(faq_answer, faq_docs))
        if faq_answer:
            result = RagQueryResult(
                answer_markdown=faq_answer.answer_markdown,
                source="faq",
                sources=[],
                steps=steps,
                token_usage=faq_answer.token_usage,
                candidate_files=[],
                faq_docs=faq_docs,
                analysis=analysis,
            )
            logger.info("[RAG][%s][pipeline.complete] source=faq faq_docs=%d duration_ms=%d", trace_id, len(faq_docs), int((time.perf_counter() - started_at) * 1000))
            return result

        prepared = await self._prepare_pageindex_context(query_input, behavior, analysis, seeds, faq_docs, trace_id=trace_id)
        steps.append(self._build_file_retrieval_step(seeds, prepared.candidate_files))

        if not prepared.candidate_files:
            result = RagQueryResult(
                answer_markdown=behavior.no_candidate_message,
                source="bypass",
                sources=[],
                steps=steps,
                token_usage=None,
                candidate_files=[],
                faq_docs=faq_docs,
                analysis=analysis,
            )
            logger.info("[RAG][%s][pipeline.complete] source=bypass faq_docs=%d duration_ms=%d", trace_id, len(faq_docs), int((time.perf_counter() - started_at) * 1000))
            return result

        logger.info("[RAG][%s][pageindex.start] candidates=%s", trace_id, [file.get("file_id") for file in prepared.candidate_files])
        agent_result = await run_pageindex_agent_loop(
            candidate_files=prepared.candidate_files,
            prompt_contents=prepared.prompt_contents,
            resolve_citations=behavior.resolve_citations,
            citation_link_type=behavior.citation_link_type,
            system_prompt=prepared.system_prompt,
            include_reasoning=behavior.include_reasoning,
            trace_id=trace_id,
        )
        agent_steps = agent_result.get("steps") or []
        result = RagQueryResult(
            answer_markdown=(
                agent_result.get("final_answer")
                or "Hệ thống chưa tổng hợp được câu trả lời từ tài liệu. Vui lòng hỏi lại cụ thể hơn."
            ),
            source="llm",
            sources=agent_result.get("sources") or [],
            steps=steps + agent_steps,
            token_usage=agent_result.get("tokenUsage"),
            candidate_files=prepared.candidate_files,
            faq_docs=faq_docs,
            max_turns_reached=bool(agent_result.get("max_turns_reached")),
            analysis=analysis,
        )
        logger.info(
            "[RAG][%s][pipeline.complete] source=pageindex candidates=%d sources=%d max_turns=%s duration_ms=%d",
            trace_id,
            len(prepared.candidate_files),
            len(result.sources),
            result.max_turns_reached,
            int((time.perf_counter() - started_at) * 1000),
        )
        return result

    async def _run_stream(
        self,
        query_input: RagQueryInput,
        behavior: RagQueryBehavior,
    ) -> AsyncGenerator[dict[str, Any], None]:
        trace_id = uuid4().hex[:12]
        logger.info(
            "[RAG][%s][stream.start] role=%s history=%d question_len=%d",
            trace_id,
            query_input.user_role,
            len(query_input.chat_history),
            len(query_input.question),
        )
        yield {"type": "_query_analysis_start", "content": "Phân tích câu hỏi của người dùng..."}
        analysis = await self._analyze(query_input, behavior)
        logger.info("[RAG][%s][stream.analysis] needs_rag=%s effective_question=%r metadata=%s", trace_id, analysis.needs_rag, analysis.effective_question[:300], analysis.metadata_filter)
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

        traversal_steps: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

        async def emit_traversal_step(step: dict[str, Any]) -> None:
            await traversal_steps.put(step)

        traversal_task = asyncio.create_task(
            self._retrieval.traverse_query(
                question=analysis.effective_question,
                metadata_filter=analysis.metadata_filter,
                user_role=query_input.user_role,
                trace_id=trace_id,
                on_traversal_step=emit_traversal_step,
            )
        )
        try:
            while not traversal_task.done():
                next_step_task = asyncio.create_task(traversal_steps.get())
                done, _ = await asyncio.wait(
                    {traversal_task, next_step_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if next_step_task in done:
                    step = next_step_task.result()
                    steps.append(step)
                    yield {"type": "_corpus_traversal", "step": step}
                else:
                    next_step_task.cancel()
                    with suppress(asyncio.CancelledError):
                        await next_step_task
            while not traversal_steps.empty():
                step = traversal_steps.get_nowait()
                steps.append(step)
                yield {"type": "_corpus_traversal", "step": step}
            seeds = await traversal_task
        except BaseException:
            if not traversal_task.done():
                traversal_task.cancel()
                with suppress(asyncio.CancelledError):
                    await traversal_task
            raise

        faq_docs: list[Any] = []
        faq_answer = None
        if seeds.faq_candidates:
            faq_docs = await self._prepare_faq_context(analysis, seeds, trace_id=trace_id)
            faq_retrieval_step = self._build_faq_retrieval_step(seeds, faq_docs)
            steps.append(faq_retrieval_step)
            yield {"type": "_pipeline_step", "step": faq_retrieval_step}
            faq_answer = await self._try_answer_from_faqs(analysis, faq_docs)
            if faq_docs:
                faq_answer_step = self._build_faq_answer_step(faq_answer, faq_docs)
                steps.append(faq_answer_step)
                yield {"type": "_pipeline_step", "step": faq_answer_step}
        if faq_answer:
            yield {
                "type": "_pipeline_result",
                "answer_markdown": faq_answer.answer_markdown,
                "source": "faq",
                "sources": [],
                "steps": steps,
                "token_usage": faq_answer.token_usage,
                "candidate_files": [],
                "faq_docs": faq_docs,
                "max_turns_reached": False,
                "analysis": analysis,
                "is_direct_reply": False,
            }
            return

        prepared = await self._prepare_pageindex_context(query_input, behavior, analysis, seeds, faq_docs, trace_id=trace_id)
        file_retrieval_step = self._build_file_retrieval_step(seeds, prepared.candidate_files)
        steps.append(file_retrieval_step)
        yield {
            "type": "_pipeline_step",
            "step": file_retrieval_step,
            "candidate_files": prepared.candidate_files,
        }

        if not prepared.candidate_files:
            yield {
                "type": "_pipeline_result",
                "answer_markdown": behavior.no_candidate_message,
                "source": "bypass",
                "sources": [],
                "steps": steps,
                "token_usage": None,
                "candidate_files": [],
                "faq_docs": faq_docs,
                "max_turns_reached": False,
                "analysis": analysis,
                "is_direct_reply": False,
            }
            return

        async for event in stream_pageindex_agent_loop(
            candidate_files=prepared.candidate_files,
            prompt_contents=prepared.prompt_contents,
            resolve_citations=behavior.resolve_citations,
            citation_link_type=behavior.citation_link_type,
            system_prompt=prepared.system_prompt,
            include_reasoning=behavior.include_reasoning,
            trace_id=trace_id,
        ):
            yield event

    async def _analyze(self, query_input: RagQueryInput, behavior: RagQueryBehavior) -> RagQueryAnalysis:
        if behavior.analyzer_mode == "chat":
            chat_analysis = await self.analyzer.analyze_query(
                query_input.question,
                query_input.chat_history,
            )
            metadata_filter = chat_analysis.metadata_filter or {}
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
                effective_question=chat_analysis.effective_question or query_input.question,
                needs_rag=bool(chat_analysis.needs_rag),
                metadata_filter=metadata_filter,
                usage=chat_analysis.usage,
            )

        if behavior.analyzer_mode == "email":
            email_analysis = await self.email_analyzer.analyze_email(
                query_input.email_subject or "",
                query_input.email_content or query_input.question,
                sender_enrollment_year=query_input.enrollment_year,
            )
            effective_question = email_analysis.question or query_input.question
            if not effective_question:
                effective_question = "\n".join(
                    part for part in [query_input.email_subject, query_input.email_content] if part
                )
            return RagQueryAnalysis(
                original_question=query_input.question,
                effective_question=effective_question,
                needs_rag=True,
                metadata_filter=email_analysis.metadata_filter,
                inquiry_types=email_analysis.inquiry_types,
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

    async def _prepare_faq_context(
        self,
        analysis: RagQueryAnalysis,
        seeds: RetrievalSeeds,
        *,
        trace_id: str = "",
    ) -> list[Any]:
        return await self._retrieval.retrieve_faq_context(
            analysis.effective_question,
            seeds.faq_candidates,
            trace_id=trace_id,
        )

    async def _prepare_pageindex_context(
        self,
        query_input: RagQueryInput,
        behavior: RagQueryBehavior,
        analysis: RagQueryAnalysis,
        seeds: RetrievalSeeds,
        faq_docs: list[Any],
        *,
        trace_id: str = "",
    ) -> RagPreparedContext:
        candidate_files = await self._retrieval.retrieve_file_context(
            analysis.effective_question,
            seeds.file_candidates,
            max_files=query_input.max_files,
            trace_id=trace_id,
        )

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
    def _build_faq_retrieval_step(seeds: RetrievalSeeds, faq_docs: list[Any]) -> dict[str, Any]:
        return {
            "type": "faq_retrieval",
            "seed_count": len(seeds.faq_candidates),
            "faq_count": len(faq_docs),
            "faq_ids": [str(getattr(faq, "id", "")) for faq in faq_docs],
        }

    @staticmethod
    def _build_faq_answer_step(faq_answer: Any | None, faq_docs: list[Any]) -> dict[str, Any]:
        if faq_answer is not None:
            return faq_answer.as_step()
        return {
            "type": "faq_answer",
            "answered": False,
            "faq_ids": [str(getattr(faq, "id", "")) for faq in faq_docs],
            "questions": [getattr(faq, "question", "") for faq in faq_docs],
        }

    @staticmethod
    def _build_file_retrieval_step(seeds: RetrievalSeeds, candidate_files: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "type": "file_retrieval",
            "seed_count": len(seeds.file_candidates),
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
            analyzer_mode=behavior.analyzer_mode,
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
