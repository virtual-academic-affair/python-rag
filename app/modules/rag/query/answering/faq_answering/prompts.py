from __future__ import annotations

from typing import Optional

from app.modules.rag.query.answering.faq_answering.contracts import FaqAnswerEntry


FAQ_ANSWER_SYSTEM_PROMPT = """Bạn là trợ lý FAQ trong RAG pipeline của hệ thống tư vấn Phòng Giáo vụ.

Bạn nhận một CÂU HỎI của người dùng và một DANH SÁCH FAQ đã được retrieval chọn trước.
Mỗi FAQ gồm ID, câu hỏi, câu trả lời Markdown, khóa và năm học.

Nhiệm vụ:
- Đọc nội dung FAQ, quyết định FAQ có đủ trả lời TOÀN BỘ câu hỏi của người dùng hay không.
- Nếu đủ, viết câu trả lời Markdown phù hợp trực tiếp với câu hỏi của người dùng.
- Nếu cần nhiều FAQ để trả lời nhiều ý độc lập, hãy dùng tất cả FAQ cần thiết và tổng hợp thành một câu trả lời mạch lạc.
- Chỉ dùng thông tin có trong FAQ được cung cấp. Không tự thêm thông tin ngoài FAQ.
- Không bắt buộc copy y nguyên answer của FAQ; hãy diễn đạt tự nhiên, ngắn gọn, đúng trọng tâm.
- Nếu FAQ chỉ trả lời được một phần, liên quan mờ nhạt, thiếu một ý độc lập, hoặc cần đọc tài liệu để chắc chắn, trả về {"answer": null}.
- Ưu tiên đúng khóa/năm học khi câu hỏi có đề cập.

CHỈ trả về JSON đúng schema:
{
  "answer": {
    "faq_ids": ["<faq id đã dùng>", "..."],
    "answer_markdown": "<câu trả lời Markdown>"
  }
}
hoặc nếu FAQ không đủ trả lời toàn bộ câu hỏi: {"answer": null}
"""


def _fmt_year(year_filter: Optional[dict]) -> str:
    if not year_filter:
        return "mọi khóa"
    from_year = year_filter.get("from_year")
    to_year = year_filter.get("to_year")
    if from_year in (None, 0) and to_year in (None, 9999):
        return "mọi khóa"
    if from_year == to_year:
        return str(from_year)
    return f"{from_year}-{to_year}"


def render_faq_answer_context(entries: list[FaqAnswerEntry]) -> str:
    blocks: list[str] = []
    for index, entry in enumerate(entries, 1):
        blocks.append(
            "\n".join([
                f"[{index}] ID: {entry.faq_id}",
                f"Câu hỏi FAQ: {entry.question}",
                f"Khóa: {_fmt_year(entry.enrollment_year)} | Năm học: {_fmt_year(entry.academic_year)}",
                "Câu trả lời FAQ:",
                entry.answer_markdown,
            ])
        )
    return "\n\n---\n\n".join(blocks)


def build_faq_answer_prompt(question: str, entries: list[FaqAnswerEntry]) -> str:
    return (
        FAQ_ANSWER_SYSTEM_PROMPT
        + f'\n\nCÂU HỎI NGƯỜI DÙNG: "{question}"\n\n'
        + f"DANH SÁCH FAQ:\n{render_faq_answer_context(entries)}\n\n"
        + "Trả về JSON:"
    )
