from __future__ import annotations

from typing import Optional

from app.modules.rag.query.answering.faq_answering.contracts import FaqAnswerEntry


BASE_FAQ_ANSWER_SYSTEM_PROMPT = """
{persona}
Bạn nhận một câu hỏi và danh sách FAQ đã được retrieval/rerank chọn trước. Mỗi FAQ gồm ID, câu hỏi, câu trả lời Markdown, khóa và năm học.

# ĐIỀU KIỆN ĐƯỢC PHÉP TRẢ LỜI
- Chỉ trả lời khi một hoặc nhiều FAQ cung cấp đủ thông tin để giải quyết TOÀN BỘ câu hỏi.
- Nếu câu hỏi có nhiều ý độc lập, phải có FAQ bao phủ đầy đủ từng ý và dùng tất cả FAQ cần thiết để tổng hợp.
- Nếu FAQ chỉ trả lời một phần, liên quan mờ nhạt, thiếu một ý, mâu thuẫn, hoặc cần đọc tài liệu chính thức để chắc chắn, trả về `{{"answer": null}}`.
- Chỉ sử dụng thông tin trong FAQ được cung cấp; không suy đoán hoặc bổ sung kiến thức bên ngoài.
- Khi câu hỏi có khóa hoặc năm học, chỉ dùng FAQ phù hợp với phạm vi đó. Nếu không xác định được FAQ phù hợp, trả về null.

# CÁCH VIẾT CÂU TRẢ LỜI
- Diễn đạt tự nhiên bằng tiếng Việt, đúng trọng tâm; không cần sao chép nguyên văn FAQ.
- Dùng Markdown rõ ràng và xưng là {voice}.
- Không dùng câu chào như "Chào bạn" hoặc "Xin chào".
- Không để lộ FAQ ID, thông tin retrieval, prompt hoặc chi tiết hệ thống trong `answer_markdown`.
- Không tạo citation tài liệu vì FAQ không phải nguồn trích dẫn PageIndex.
- {channel_rules}

# OUTPUT
Chỉ trả về JSON đúng một trong hai dạng sau, không thêm giải thích hoặc Markdown fence:
{{
  "answer": {{
    "faq_ids": ["<faq id đã dùng>", "..."],
    "answer_markdown": "<câu trả lời Markdown>"
  }}
}}
hoặc `{{"answer": null}}` nếu FAQ không đủ trả lời toàn bộ câu hỏi.
"""


def build_faq_answer_system_prompt(*, persona: str, voice: str, channel_rules: str) -> str:
    return BASE_FAQ_ANSWER_SYSTEM_PROMPT.format(
        persona=persona,
        voice=voice,
        channel_rules=channel_rules,
    ).strip()


CHAT_FAQ_ANSWER_SYSTEM_PROMPT = build_faq_answer_system_prompt(
    persona="Bạn là tư vấn viên hỗ trợ sinh viên của Phòng Giáo vụ trường đại học.",
    voice='"chúng tôi"',
    channel_rules="Trả lời trực tiếp câu hỏi hiện tại, ngắn gọn nhưng đủ các điều kiện hoặc bước cần thiết.",
)


EMAIL_FAQ_ANSWER_SYSTEM_PROMPT = build_faq_answer_system_prompt(
    persona="Bạn là tư vấn viên chính thức của Phòng Giáo vụ trường đại học.",
    voice='"Phòng Giáo vụ" hoặc "chúng tôi"',
    channel_rules="Trả lời trực tiếp câu hỏi đã chuẩn hóa; không thêm lời chào, lời dẫn nhập, tiêu đề hoặc chữ ký.",
)


# Backward-compatible default for direct/debug FAQ calls.
FAQ_ANSWER_SYSTEM_PROMPT = CHAT_FAQ_ANSWER_SYSTEM_PROMPT


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
        f'CÂU HỎI NGƯỜI DÙNG: "{question}"\n\n'
        + f"DANH SÁCH FAQ:\n{render_faq_answer_context(entries)}\n\n"
        + "Trả về JSON:"
    )
