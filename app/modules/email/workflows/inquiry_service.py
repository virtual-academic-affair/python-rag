"""Inquiry workflow service: email workflow adapter around the shared RAG query pipeline."""
import asyncio
import logging
import time
from typing import Any, Dict, Optional

from app.modules.faq.services.faq_service import get_faq_service
from app.modules.rag.query import RagQueryInput, get_rag_query_pipeline
from app.utils.format_utils import markdown_to_rich_text

logger = logging.getLogger(__name__)

class InquiryService:
    def __init__(self):
        self._rag_query = get_rag_query_pipeline()

    def _get_rag_query(self):
        if not hasattr(self, "_rag_query") or self._rag_query is None:
            self._rag_query = get_rag_query_pipeline()
        return self._rag_query

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
        Run the shared RAG query pipeline and adapt the result for email workflow.
        """
        start_time = time.time()
        logger.info("[Inquiry] Starting email RAG pipeline...")
        rag_result = await self._get_rag_query().answer_email(
            RagQueryInput(
                mode="email",
                question=f"{title}\n{content}".strip(),
                user_role=user_role,
                email_subject=title,
                email_content=content,
                enrollment_year=enrollment_year,
                resolve_citations=True,
                citation_link_type="original",
            )
        )

        query_analysis = rag_result.analysis
        extracted_question = query_analysis.effective_question if query_analysis else f"{title}\n{content}".strip()
        inquiry_types = query_analysis.inquiry_types if query_analysis else []
        metadata_filter = query_analysis.metadata_filter if query_analysis else {}
        candidate_files = rag_result.candidate_files
        faq_docs = rag_result.faq_docs
        logger.info(
            "[Inquiry] Retrieval: %s files, %s supporting FAQs",
            len(candidate_files),
            len(faq_docs),
        )

        processing_time_ms = int((time.time() - start_time) * 1000)
        answer_markdown = rag_result.answer_markdown
        logger.info(
            "[Inquiry] Done in %.2fs | Source: %s | Answer length: %s",
            processing_time_ms / 1000,
            rag_result.source,
            len(answer_markdown),
        )

        if rag_result.source != "bypass":
            faq_svc = await get_faq_service()
            asyncio.create_task(faq_svc.log_interaction(
                question=extracted_question,
                answer_markdown=answer_markdown,
                metadata_filter=metadata_filter,
                source_type="inquiry_email",
                processing_time_ms=processing_time_ms,
                email_message_id=message_id,
            ))

        final_answer = answer_markdown
        if to_rich_text:
            final_answer = markdown_to_rich_text(final_answer)

        logger.info(f"[Inquiry] Final answer returned (first 300 chars): {final_answer[:300]!r}")
        return {
            "answer": final_answer,
            "sources": rag_result.sources if rag_result.source != "faq" else [],
            "source": rag_result.source,
            "question": extracted_question,
            "types": inquiry_types,
            "filters": metadata_filter,
            "message_id": message_id
        }
