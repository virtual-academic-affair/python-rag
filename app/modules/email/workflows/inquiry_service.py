"""Inquiry workflow service: RAG reply generation via corpus traversal.

Luồng giống chat (chat_service): corpus traversal (pre-filter 3 key,
role=student) → FAQ fast-path → agent loop đọc tài liệu. Giữ phần extraction
riêng của email (unified extraction + regex/cohort fallback).
"""
import logging
from typing import Dict, Any, Optional, List

from langchain_core.prompts import ChatPromptTemplate
from app.core.config import settings
from app.integrations.llm.gemini import build_extraction_llm
from app.modules.rag.retrieval.retrieval_service import get_retrieval_service
from app.modules.rag.corpus.services.corpus_traversal_service import get_corpus_traversal_service
from app.modules.rag.corpus.dtos.traversal import TraversalResult
from app.modules.rag.faq import fetch_supporting_faqs, build_faq_context, try_faq_fast_path
from app.modules.rag.agent import run_agent_loop, EMAIL_SYSTEM_PROMPT
from app.modules.metadata.services.extraction_service import extract_metadata_from_text
from app.modules.email.utils.email_utils import extract_structured_data
from app.modules.faq.services.faq_service import get_faq_service
from app.utils.format_utils import markdown_to_rich_text
import asyncio
import time

logger = logging.getLogger(__name__)

class InquiryService:
    def __init__(self):
        self._retrieval = get_retrieval_service()
        self._extraction_llm = build_extraction_llm(
            api_key=settings.GOOGLE_API_KEY,
            model=settings.GEMINI_MODEL,
            temperature=0.0
        )
        
        # Unified prompt for extracting intent, types, and metadata filters in one call
        self.extraction_prompt = ChatPromptTemplate.from_messages([
            ("system", (
                "Bạn là chuyên gia phân tích email giáo vụ cho hệ thống tư vấn Phòng Giáo vụ.\n"
                "Hãy phân tích email dưới đây (bao gồm Tiêu đề và Nội dung) để trích xuất dữ liệu sau:\n\n"
                "1. 'question': Câu hỏi chính hoặc ý định cốt lõi của người dùng.\n"
                "   - Viết lại thành câu HOÀN CHỈNH, TỰ LẬP (không cần ngữ cảnh tiêu đề/nội dung để hiểu).\n"
                "   - Điền đầy đủ thông tin ngầm hiểu (khóa học, năm học, chủ đề đang hỏi).\n"
                "   - Giữ nguyên Tiếng Việt, KHÔNG thay đổi ý nghĩa gốc.\n"
                "2. 'inquiry_types': Danh sách các loại thắc mắc (chọn từ: ['graduation', 'training']).\n"
                "   - 'graduation': Các vấn đề liên quan đến tốt nghiệp, xét tốt nghiệp, chứng nhận, bằng cấp.\n"
                "   - 'training': Các vấn đề về đào tạo, học phần, đăng ký học tập, thời khóa biểu, điểm số, học vụ.\n"
                "   - Nếu không rõ ràng hoặc thuộc loại khác, mặc định chọn ['training'].\n"
                "3. 'metadata_filter': Trích xuất bộ lọc năm học (academic_year) và khóa tuyển sinh (enrollment_year) từ toàn bộ ngữ cảnh email:\n"
                "   - 'enrollment_year': Khóa sinh viên. Quy tắc BẮT BUỘC: \"K22\" hoặc \"Khóa 22\" -> from_year=2022, to_year=2022.\n"
                "     Công thức: năm = 2000 + số sau K (ví dụ K20 -> 2020, K19 -> 2019, K22 -> 2022). TUYỆT ĐỐI KHÔNG suy diễn khác. Thiết lập: {{\"from_year\": năm, \"to_year\": năm}}.\n"
                "   - 'academic_year': Năm học.\n"
                "     + Nếu có dạng cụ thể như \"NH 2024-2025\" hoặc \"năm học 24-25\" -> from_year=2024, to_year=2025.\n"
                "     + Nếu chỉ có dạng \"năm học 2024\" -> from_year=2024, to_year=2024.\n"
                "     + QUY TẮC ĐẶC BIỆT KHI CÓ NIÊN KHÓA: Nếu trích xuất được enrollment_year (K) và email đề cập đến năm học thứ N (năm nhất/1, năm hai/2,...) của khóa đó:\n"
                "       * Tính toán: from_year = K + N - 1, to_year = K + N.\n"
                "       * Ví dụ: Năm nhất (năm 1) của khóa 22 (enrollment_year=2022) -> academic_year: from_year=2022, to_year=2023 (Năm học 2022-2023).\n"
                "       * Ví dụ: Năm tư (năm 4) của khóa 22 (enrollment_year=2022) -> academic_year: from_year=2025, to_year=2026 (Năm học 2025-2026).\n"
                "   - Nếu không tìm thấy thông tin tương ứng -> null.\n\n"
                "Trả về DUY NHẤT một đối tượng JSON hợp lệ theo schema sau (không có ký tự nào khác ngoài JSON):\n"
                "{{\n"
                "  \"question\": string,\n"
                "  \"inquiry_types\": [string],\n"
                "  \"metadata_filter\": {{\n"
                "    \"enrollment_year\": {{\n"
                "      \"from_year\": integer,\n"
                "      \"to_year\": integer\n"
                "    }} | null,\n"
                "    \"academic_year\": {{\n"
                "      \"from_year\": integer,\n"
                "      \"to_year\": integer\n"
                "    }} | null\n"
                "  }} | null\n"
                "}}"
            )),
            ("human", "Tiêu đề: {title}\nNội dung:\n{content}")
        ])

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
        1. Unified Extraction (Intent, Types, and Filters) via Gemini.
        2. Retrieve Answer via RetrievalService (RAG).
        """
        start_time = time.time()
        # 1. Unified Extraction (Call LLM only once)
        logger.info(f"[Inquiry] Starting unified extraction...")
        extraction_data = await extract_structured_data(
            self._extraction_llm, 
            self.extraction_prompt, 
            {"title": title, "content": content}
        )
        dur_extraction = time.time() - start_time
        extracted_question = extraction_data.get("question")
        inquiry_types = extraction_data.get("inquiry_types", ["training"])
        metadata_filter = extraction_data.get("metadata_filter") or {}
        logger.info(f"[Inquiry] QueryAnalysis done in {dur_extraction:.2f}s | Result: {extraction_data}")

        # 2. Xử lý bộ lọc enrollment_year & academic_year với Regex Fallback và RabbitMQ Fallback
        # Chỉ chạy regex khi LLM không tìm được cả hai
        if not metadata_filter.get("enrollment_year") and not metadata_filter.get("academic_year"):
            regex_filter = await extract_metadata_from_text(f"{title} {content}")
            if regex_filter:
                if regex_filter.get("enrollment_year"):
                    logger.info(f"[Inquiry] Fallback enrollment_year to Regex: {regex_filter['enrollment_year']}")
                    metadata_filter["enrollment_year"] = regex_filter["enrollment_year"]
                if regex_filter.get("academic_year"):
                    logger.info(f"[Inquiry] Fallback academic_year to Regex: {regex_filter['academic_year']}")
                    metadata_filter["academic_year"] = regex_filter["academic_year"]

            # Nếu Regex vẫn không tìm thấy enrollment_year, thì fallback về khóa sinh viên gửi từ RabbitMQ
            if not metadata_filter.get("enrollment_year") and enrollment_year:
                logger.info(f"[Inquiry] Fallback enrollment_year to RabbitMQ sender cohort: {enrollment_year}")
                metadata_filter["enrollment_year"] = {
                    "from_year": enrollment_year,
                    "to_year": enrollment_year
                }
        
        logger.info(f"[Inquiry] Final metadata_filter applied: {metadata_filter}")

        # 3. RAG Step (corpus traversal → FAQ fast-path → agent loop, giống chat)
        rag_query = extracted_question or f"{title}\n{content}"
        rag_result = await self._run_rag_pipeline(rag_query, title, content, metadata_filter)

        processing_time_ms = int((time.time() - start_time) * 1000)
        logger.info(f"[Inquiry] Done in {processing_time_ms / 1000:.2f}s | Source: {rag_result.get('source')} | Answer length: {len(rag_result['answer'])}")

        # Log async interaction (bỏ qua khi trả lời trực tiếp từ FAQ để tránh log trùng)
        if rag_result.get("source") != "faq":
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
        Luồng RAG giống chat: corpus traversal → FAQ fast-path → agent loop.
        Người gửi email luôn là sinh viên → user_role="student" (tự động ẩn
        tài liệu/FAQ lecturer_only nhờ pre-filter 3 key).
        Trả về {"answer", "sources", "source"} với source ∈ {faq, llm, bypass}.
        """
        # Stage 2 — corpus traversal (best-effort như chat)
        traversal_svc = get_corpus_traversal_service()
        try:
            result = await traversal_svc.traverse(
                rag_query,
                metadata_filter=metadata_filter or None,
                user_role="student",
            )
        except Exception as e:
            logger.warning(f"[Inquiry] traverse failed (best-effort): {e}")
            result = TraversalResult()

        candidate_files = await self._retrieval.enrich_corpus_candidates(result.file_candidates)
        faq_docs = await fetch_supporting_faqs(result.supporting_faqs)
        logger.info(
            f"[Inquiry] Retrieval: {len(candidate_files)} files, {len(faq_docs)} supporting FAQs"
        )

        # Stage 3 — FAQ fast-path
        faq_answer = await try_faq_fast_path(rag_query, faq_docs)
        if faq_answer:
            logger.info("[Inquiry] FAQ fast-path answer")
            return {"answer": faq_answer, "sources": [], "source": "faq"}

        # Stage 4 — đọc tài liệu qua agent loop
        if not candidate_files:
            logger.warning("[Inquiry] No candidate files and no FAQ match.")
            return {
                "answer": "Không tìm thấy tài liệu phù hợp để trả lời email này.",
                "sources": [],
                "source": "bypass",
            }

        faq_context = build_faq_context(faq_docs)
        files_info_str = "\n".join(
            f"- ID: {c['file_id']} | Name: {c['file_name']} | Description: {c.get('doc_description', '')}"
            for c in candidate_files
        )
        context_str = self._build_metadata_context(metadata_filter)
        prompt_text = (
            f"Email Subject: {title}\n"
            f"Email Body:\n{content}\n\n"
            f"{faq_context}"
            f"{context_str}"
            f"Relevant documents found:\n{files_info_str}\n\n"
            f"Please answer the user's specific inquiry based on these documents. "
            f"Respect the specific rules for the given academic year and cohort if provided."
        )

        agent_result = await run_agent_loop(
            candidate_files=candidate_files,
            prompt_contents=prompt_text,
            resolve_citations=True,
            citation_link_type="original",
            system_prompt=EMAIL_SYSTEM_PROMPT,
        )
        return {
            "answer": agent_result["final_answer"] or "Xin lỗi, tôi không thể tìm thấy câu trả lời chính xác.",
            "sources": agent_result["sources"],
            "source": "llm",
        }

    @staticmethod
    def _build_metadata_context(metadata_filter: Dict[str, Any]) -> str:
        """Khối 'Context Information' (năm học/khóa) để agent tôn trọng ràng buộc năm."""
        context_blocks = []
        if metadata_filter.get("academic_year"):
            ay = metadata_filter["academic_year"]
            f_yr = ay.get("from_year") or ay.get("fromYear")
            t_yr = ay.get("to_year") or ay.get("toYear")
            context_blocks.append(f"Academic Year: {f_yr}-{t_yr}")
        if metadata_filter.get("enrollment_year"):
            ey = metadata_filter["enrollment_year"]
            f_yr = ey.get("from_year") or ey.get("fromYear")
            t_yr = ey.get("to_year") or ey.get("toYear")
            context_blocks.append(f"Enrollment Year: {f_yr}-{t_yr}")
        return f"Context Information: [{', '.join(context_blocks)}]\n\n" if context_blocks else ""
