"""
QueryAnalyzer — Phân tích câu hỏi chat: rewrite, gate, metadata.
Tách biệt hoàn toàn với ChatService để dễ test và maintain.
"""
import json
import logging
from typing import Optional, List, Dict, Any

from google.genai import types

from app.core.config import settings
from app.integrations.llm.gemini import gemini_client
from app.modules.chat.schemas import ChatHistoryItem
from app.utils.json_utils import parse_json_safely
from app.utils.retry import async_retry

logger = logging.getLogger(__name__)

ANALYZE_SYSTEM_PROMPT = """
Bạn là chuyên gia phân tích ngữ cảnh hội thoại cho hệ thống tư vấn Phòng Giáo vụ.

Dựa vào lịch sử hội thoại (nếu có) và câu hỏi hiện tại, hãy thực hiện 3 nhiệm vụ:

**NHIỆM VỤ 1 — effective_question:**
Viết lại câu hỏi thành câu HOÀN CHỈNH, TỰ LẬP (không cần ngữ cảnh để hiểu).
- Điền đầy đủ thông tin ngầm hiểu từ lịch sử (khóa học, năm học, chủ đề đang hỏi).
- Giữ nguyên Tiếng Việt. KHÔNG thay đổi ý nghĩa gốc.
- Nếu câu hỏi đã rõ ràng, trả về nguyên văn.

**NHIỆM VỤ 2 — needs_rag:**
Câu hỏi (sau khi rewrite) có cần tra cứu tài liệu quy chế, thủ tục, thông báo học vụ không?
- true: Hỏi về quy định, điều kiện, thủ tục, học phần, tốt nghiệp, học bổng, học phí, lịch học...
- false: Lời chào hỏi, cảm ơn, xã giao thông thường, câu hỏi hoàn toàn ngoài phạm vi học vụ.

**NHIỆM VỤ 3 — metadata_filter:**
Trích xuất thông tin lọc từ TOÀN BỘ ngữ cảnh (câu hỏi + lịch sử):
- enrollment_year: Khóa sinh viên. Quy tắc BẮT BUỘC: "K22" hoặc "Khóa 22" -> from_year=2022, to_year=2022.
  Công thức: năm = 2000 + số sau K (ví dụ K20 -> 2020, K19 -> 2019, K22 -> 2022). TUYỆT ĐỐI KHÔNG suy diễn khác.
- academic_year: Năm học.
  + Nếu có dạng cụ thể như "NH 2024-2025" hoặc "năm học 24-25" -> from_year=2024, to_year=2025.
  + Nếu chỉ có dạng "năm học 2024" -> from_year=2024, to_year=2024.
  + QUY TẮC ĐẶC BIỆT KHI CÓ NIÊN KHÓA: Nếu trích xuất được enrollment_year (K) và người dùng đề cập đến năm học thứ N (năm nhất/1, năm hai/2,...) của khóa đó:
    * Tính toán: from_year = K + N - 1, to_year = K + N.
    * Ví dụ: Năm nhất (năm 1) của khóa 22 (enrollment_year=2022) -> academic_year: from_year=2022, to_year=2023 (Năm học 2022-2023).
    * Ví dụ: Năm tư (năm 4) của khóa 22 (enrollment_year=2022) -> academic_year: from_year=2025, to_year=2026 (Năm học 2025-2026).
- Nếu không tìm thấy thông tin tương ứng -> null.

**OUTPUT FORMAT — Chỉ trả về JSON hợp lệ theo schema sau:**
{
  "needs_rag": true | false,
  "effective_question": "...",
  "metadata_filter": {
    "enrollment_year": {"from_year": int, "to_year": int} | null,
    "academic_year": {"from_year": int, "to_year": int} | null
  } | null
}
"""

GENERATE_REPLY_SYSTEM_PROMPT = """
Bạn là tư vấn viên hỗ trợ sinh viên của trường đại học.
Hãy trả lời câu hỏi/lời nhắn của sinh viên một cách lịch sự, ngắn gọn và thân thiện.
KHÔNG dùng lời chào đầu câu. Đi thẳng vào nội dung phản hồi.
Giới hạn: 2-3 câu.
"""

class QueryAnalyzer:
    async def analyze_query(
        self,
        question: str,
        history: List[ChatHistoryItem],
    ) -> Dict[str, Any]:
        """
        Phân tích câu hỏi và trả về:
        {
          "needs_rag": bool,
          "effective_question": str,
          "metadata_filter": dict | None
        }
        """
        fallback_res = {
            "needs_rag": True,
            "effective_question": question,
            "metadata_filter": None
        }

        async def fallback_regex():
            try:
                from app.modules.metadata.extraction import extract_metadata_from_text
                regex_filter = await extract_metadata_from_text(question)
                if regex_filter:
                    logger.info(f"[Analyzer] Fallback to regex metadata extraction for chat query: {regex_filter}")
                    fallback_res["metadata_filter"] = regex_filter
            except Exception as fe:
                logger.warning(f"[Analyzer] Failed during fallback regex extraction: {fe}")
            return fallback_res

        try:
            history_str = "\n".join([f"{'User' if h.role == 'user' else 'Assistant'}: {h.content}" for h in history])
            
            prompt = (
                f"{ANALYZE_SYSTEM_PROMPT}\n\n"
                f"Lịch sử hội thoại:\n{history_str}\n\n"
                f"Câu hỏi hiện tại: \"{question}\"\n"
                f"Trả về kết quả dưới dạng JSON:"
            )

            resp = await async_retry(
                gemini_client.client.aio.models.generate_content,
                model=settings.GEMINI_MODEL,
                contents=[prompt],
                config=types.GenerateContentConfig(
                    temperature=0.0,
                    response_mime_type="application/json"
                )
            )

            if not resp.text:
                logger.warning("[Analyzer] Empty response from LLM, using fallback.")
                return await fallback_regex()

            data = parse_json_safely(resp.text, repair=True)
            logger.info(f"[Analyzer] Input question: '{question}' | Analysis result: {data}")

            needs_rag = data.get("needs_rag", True)
            effective_question = data.get("effective_question") or question
            metadata_filter = data.get("metadata_filter")

            # Clean metadata_filter if empty fields
            if metadata_filter:
                enrollment_year = metadata_filter.get("enrollment_year")
                academic_year = metadata_filter.get("academic_year")
                if not enrollment_year and not academic_year:
                    metadata_filter = None
                else:
                    # Ensure from_year and to_year are set correctly
                    if enrollment_year and (enrollment_year.get("from_year") is None or enrollment_year.get("to_year") is None):
                        metadata_filter["enrollment_year"] = None
                    if academic_year and (academic_year.get("from_year") is None or academic_year.get("to_year") is None):
                        metadata_filter["academic_year"] = None

            # Fallback to regex-based extraction if LLM didn't find filters
            if not metadata_filter or (not metadata_filter.get("enrollment_year") and not metadata_filter.get("academic_year")):
                from app.modules.metadata.extraction import extract_metadata_from_text
                regex_filter = await extract_metadata_from_text(question)
                if regex_filter:
                    logger.info(f"[Analyzer] Fallback to regex metadata extraction for chat query: {regex_filter}")
                    if metadata_filter:
                        metadata_filter.update(regex_filter)
                    else:
                        metadata_filter = regex_filter

            return {
                "needs_rag": needs_rag,
                "effective_question": effective_question,
                "metadata_filter": metadata_filter
            }

        except Exception as e:
            logger.error(f"[Analyzer] Error during analyze_query: {e}", exc_info=True)
            return await fallback_regex()

    async def generate_reply(
        self,
        effective_question: str,
        history: List[ChatHistoryItem],
    ) -> str:
        """
        Sinh câu trả lời trực tiếp (khi needs_rag=false).
        """
        try:
            history_str = "\n".join([f"{'User' if h.role == 'user' else 'Assistant'}: {h.content}" for h in history])
            prompt = (
                f"{GENERATE_REPLY_SYSTEM_PROMPT}\n\n"
                f"Lịch sử hội thoại:\n{history_str}\n\n"
                f"Tin nhắn hiện tại của sinh viên: \"{effective_question}\"\n"
                f"Câu phản hồi của bạn:"
            )

            resp = await async_retry(
                gemini_client.client.aio.models.generate_content,
                model=settings.GEMINI_MODEL,
                contents=[prompt],
                config=types.GenerateContentConfig(
                    temperature=0.7
                )
            )

            return (resp.text or "").strip() or "Phòng Giáo vụ sẵn sàng hỗ trợ. Bạn cần tra cứu thông tin gì?"
        except Exception as e:
            logger.error(f"[Analyzer] Error during generate_reply: {e}", exc_info=True)
            return "Phòng Giáo vụ sẵn sàng hỗ trợ. Bạn cần tra cứu thông tin gì?"


_analyzer_instance: Optional[QueryAnalyzer] = None

def get_query_analyzer() -> QueryAnalyzer:
    global _analyzer_instance
    if _analyzer_instance is None:
        _analyzer_instance = QueryAnalyzer()
    return _analyzer_instance
