"""Email query analyzer: normalize subject/body into a RAG-ready query."""
from __future__ import annotations

import logging
from typing import Any, Optional

from langchain_core.prompts import ChatPromptTemplate

from app.core.config import settings
from app.integrations.llm.gemini import GeminiGenAIChat, build_extraction_llm, chain_prompt
from app.modules.metadata.services.extraction_service import extract_metadata_from_text
from app.modules.rag.query.analyzer.contracts import EmailQueryAnalysis
from app.utils.json_utils import parse_json_safely
from app.utils.retry import async_retry

logger = logging.getLogger(__name__)


EMAIL_QUERY_ANALYZE_SYSTEM_PROMPT = (
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
)


class EmailQueryAnalyzer:
    """Analyze email subject/body into normalized query intent and filters."""

    def __init__(self, extraction_llm: GeminiGenAIChat | None = None):
        self._extraction_llm = extraction_llm or build_extraction_llm(
            api_key=settings.GOOGLE_API_KEY,
            model=settings.GEMINI_MODEL,
            temperature=0.0,
        )
        self.extraction_prompt = ChatPromptTemplate.from_messages([
            ("system", EMAIL_QUERY_ANALYZE_SYSTEM_PROMPT),
            ("human", "Tiêu đề: {title}\nNội dung:\n{content}"),
        ])

    async def analyze_email(
        self,
        title: str,
        content: str,
        sender_enrollment_year: int | None = None,
    ) -> EmailQueryAnalysis:
        extraction_data = await self._extract_structured_data(title, content)
        question = extraction_data.get("question")
        inquiry_types = self._normalize_inquiry_types(extraction_data.get("inquiry_types"))
        metadata_filter = self._normalize_metadata_filter(extraction_data.get("metadata_filter"))

        if not metadata_filter.get("enrollment_year") and not metadata_filter.get("academic_year"):
            regex_filter = await extract_metadata_from_text(f"{title} {content}")
            if regex_filter:
                logger.info("[EmailAnalyzer] Fallback metadata extraction: %s", regex_filter)
                metadata_filter.update(regex_filter)

            if not metadata_filter.get("enrollment_year") and sender_enrollment_year:
                logger.info(
                    "[EmailAnalyzer] Fallback enrollment_year to sender cohort: %s",
                    sender_enrollment_year,
                )
                metadata_filter["enrollment_year"] = {
                    "from_year": sender_enrollment_year,
                    "to_year": sender_enrollment_year,
                }

        return EmailQueryAnalysis(
            question=question,
            inquiry_types=inquiry_types,
            metadata_filter=metadata_filter,
        )

    async def _extract_structured_data(self, title: str, content: str) -> dict[str, Any]:
        try:
            chain = chain_prompt(self.extraction_prompt, self._extraction_llm)
            result = await async_retry(chain.ainvoke, {"title": title, "content": content})
            return parse_json_safely(result.content or "", repair=True)
        except Exception as exc:
            logger.error("[EmailAnalyzer] Error during email inquiry analysis: %s", exc, exc_info=True)
            return {}

    @staticmethod
    def _normalize_inquiry_types(raw_types: Any) -> list[str]:
        if isinstance(raw_types, str):
            raw_types = [raw_types]
        if not isinstance(raw_types, list):
            return ["training"]

        allowed = {"graduation", "training"}
        normalized = [item for item in raw_types if isinstance(item, str) and item in allowed]
        return normalized or ["training"]

    @staticmethod
    def _normalize_metadata_filter(raw_filter: Any) -> dict[str, Any]:
        if not isinstance(raw_filter, dict):
            return {}

        metadata_filter: dict[str, Any] = {}
        enrollment_year = raw_filter.get("enrollment_year")
        academic_year = raw_filter.get("academic_year")

        if EmailQueryAnalyzer._valid_year_range(enrollment_year):
            metadata_filter["enrollment_year"] = enrollment_year
        if EmailQueryAnalyzer._valid_year_range(academic_year):
            metadata_filter["academic_year"] = academic_year
        return metadata_filter

    @staticmethod
    def _valid_year_range(value: Any) -> bool:
        return (
            isinstance(value, dict)
            and value.get("from_year") is not None
            and value.get("to_year") is not None
        )


_email_query_analyzer_instance: Optional[EmailQueryAnalyzer] = None


def get_email_query_analyzer() -> EmailQueryAnalyzer:
    global _email_query_analyzer_instance
    if _email_query_analyzer_instance is None:
        _email_query_analyzer_instance = EmailQueryAnalyzer()
    return _email_query_analyzer_instance
