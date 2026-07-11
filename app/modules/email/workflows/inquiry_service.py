"""Inquiry workflow service: email workflow adapter around the shared RAG query pipeline."""
import asyncio
import logging
import time
from typing import Any, Dict, Optional

from app.modules.faq.services.faq_service import get_faq_service
from app.modules.rag.query import RagQueryInput, get_rag_query_pipeline
from app.modules.rag.query.analyzer import get_email_query_analyzer
from app.utils.format_utils import markdown_to_rich_text

logger = logging.getLogger(__name__)

class InquiryService:
    def __init__(self):
        self._rag_query = get_rag_query_pipeline()
        self._email_analyzer = get_email_query_analyzer()

    def _get_rag_query(self):
        if not hasattr(self, "_rag_query") or self._rag_query is None:
            self._rag_query = get_rag_query_pipeline()
        return self._rag_query

    def _get_email_analyzer(self):
        if not hasattr(self, "_email_analyzer") or self._email_analyzer is None:
            self._email_analyzer = get_email_query_analyzer()
        return self._email_analyzer

    async def process(
        self,
        title: str,
        content: str,
        message_id: Optional[int] = None,
        user_role: str = "student",
        to_rich_text: bool = True,
        student_code: str | None = None,
        enrollment_year: int | None = None,
    ) -> Dict[str, Any]:
        """
        Inquiry Workflow:
        1. Analyze email intent/types/filters.
        2. Retrieve Answer via shared RAG query pipeline.
        """
        start_time = time.time()
        logger.info("[Inquiry] Starting email query analysis...")
        analysis = await self._get_email_analyzer().analyze_email(
            title,
            content,
            sender_enrollment_year=enrollment_year,
        )
        dur_extraction = time.time() - start_time
        extracted_question = analysis.question
        inquiry_types = analysis.inquiry_types
        metadata_filter = analysis.metadata_filter
        logger.info("[Inquiry] QueryAnalysis done in %.2fs | Result: %s", dur_extraction, analysis)

        # RAG Step: corpus traversal -> agent loop. FAQ remains supporting context.
        rag_query = extracted_question or f"{title}\n{content}"
        rag_result = await self._run_rag_pipeline(rag_query, title, content, metadata_filter)

        processing_time_ms = int((time.time() - start_time) * 1000)
        logger.info(f"[Inquiry] Done in {processing_time_ms / 1000:.2f}s | Source: {rag_result.get('source')} | Answer length: {len(rag_result['answer'])}")

        if rag_result.get("source") != "bypass":
            faq_svc = await get_faq_service()
            asyncio.create_task(faq_svc.log_interaction(
                question=rag_query,
                answer_markdown=rag_result["answer"],
                metadata_filter=metadata_filter,
                source_type="inquiry_email",
                processing_time_ms=processing_time_ms,
                email_message_id=message_id,
            ))

        # Convert to rich text if needed
        final_answer = rag_result["answer"]
        if to_rich_text:
            final_answer = markdown_to_rich_text(final_answer)

        logger.info(f"[Inquiry] Final answer returned (first 300 chars): {final_answer[:300]!r}")
        return {
            "answer": final_answer,
            "sources": rag_result["sources"],
            "source": rag_result.get("source"),
            "question": extracted_question,
            "types": inquiry_types,
            "filters": metadata_filter,
            "message_id": message_id
        }

    async def _run_rag_pipeline(
        self,
        rag_query: str,
        title: str,
        content: str,
        metadata_filter: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Luồng RAG giống chat: corpus traversal → agent loop (FAQ là ngữ cảnh bổ trợ).
        Người gửi email luôn là sinh viên → user_role="student" (tự động ẩn
        tài liệu/FAQ lecturer_only nhờ pre-filter 3 key).
        Trả về {"answer", "sources", "source"} với source ∈ {llm, bypass}.
        """
        rag_result = await self._get_rag_query().answer_email(
            RagQueryInput(
                mode="email",
                question=rag_query,
                user_role="student",
                metadata_filter=metadata_filter,
                email_subject=title,
                email_content=content,
                resolve_citations=True,
                citation_link_type="original",
            )
        )
        candidate_files = rag_result.candidate_files
        faq_docs = rag_result.faq_docs
        logger.info(
            f"[Inquiry] Retrieval: {len(candidate_files)} files, {len(faq_docs)} supporting FAQs"
        )

        if rag_result.source == "faq":
            return {
                "answer": rag_result.answer_markdown,
                "sources": [],
                "source": "faq",
            }

        if not candidate_files:
            logger.warning("[Inquiry] No candidate files and no full FAQ match. Bypassing.")
            return {
                "answer": rag_result.answer_markdown,
                "sources": [],
                "source": "bypass",
            }

        return {
            "answer": rag_result.answer_markdown or "Xin lỗi, tôi không thể tìm thấy câu trả lời chính xác.",
            "sources": rag_result.sources,
            "source": rag_result.source,
        }
