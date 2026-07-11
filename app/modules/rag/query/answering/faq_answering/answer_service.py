from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any, Optional

from google.genai import types

from app.core.config import settings
from app.integrations.llm.gemini import gemini_client
from app.modules.faq.repositories.faq_repository import FaqRepository
from app.utils.retry import async_retry

logger = logging.getLogger(__name__)


@dataclass
class FaqAnswerEntry:
    faq_id: str
    question: str
    answer_markdown: str
    enrollment_year: Optional[dict] = None
    academic_year: Optional[dict] = None


@dataclass
class FaqAnswerResult:
    answer_markdown: str
    matched_faqs: list[Any]
    token_usage: dict[str, Any] | None = None

    def as_step(self) -> dict[str, Any]:
        return {
            "type": "faq_match",
            "faq_ids": [str(getattr(faq, "id", "")) for faq in self.matched_faqs],
            "questions": [getattr(faq, "question", "") for faq in self.matched_faqs],
        }


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


def _loads_tolerant(raw_text: str) -> Any:
    text = (raw_text or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1] if "\n" in text else ""
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return None


def parse_faq_answer_response(raw_text: str, valid_faq_ids: set[str]) -> Optional[dict[str, Any]]:
    data = _loads_tolerant(raw_text)
    if not isinstance(data, dict):
        return None

    answer = data.get("answer")
    if answer is None:
        return None
    if not isinstance(answer, dict):
        return None

    faq_ids = answer.get("faq_ids")
    answer_markdown = answer.get("answer_markdown")
    if not isinstance(faq_ids, list) or not faq_ids:
        return None
    if not isinstance(answer_markdown, str) or not answer_markdown.strip():
        return None

    normalized_ids: list[str] = []
    seen_ids: set[str] = set()
    for faq_id in faq_ids:
        if not isinstance(faq_id, str):
            return None
        if faq_id not in valid_faq_ids:
            return None
        if faq_id in seen_ids:
            continue
        seen_ids.add(faq_id)
        normalized_ids.append(faq_id)

    return {
        "faq_ids": normalized_ids,
        "answer_markdown": answer_markdown.strip(),
    }


class FaqAnswerService:
    """Generate a direct answer from retrieved FAQ context when it fully covers the query."""

    def __init__(self):
        self._faq_repo = FaqRepository()

    async def _llm_answer(self, prompt: str) -> tuple[str, dict[str, int] | None]:
        model = settings.FAQ_MATCHER_MODEL or settings.GEMINI_MODEL
        resp = await async_retry(
            gemini_client.client.aio.models.generate_content,
            model=model,
            contents=[prompt],
            config=types.GenerateContentConfig(
                temperature=0.0,
                response_mime_type="application/json",
            ),
        )
        usage = None
        if hasattr(resp, "usage_metadata") and resp.usage_metadata:
            prompt_tokens = getattr(resp.usage_metadata, "prompt_token_count", 0) or 0
            completion_tokens = getattr(resp.usage_metadata, "candidates_token_count", 0) or 0
            usage = {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            }
        return resp.text or "{}", usage

    async def answer(
        self,
        question: str,
        faq_docs: list[Any],
        *,
        increment_view_count: bool = True,
    ) -> Optional[FaqAnswerResult]:
        if not faq_docs:
            return None

        entries = self._build_entries(faq_docs)
        prompt = build_faq_answer_prompt(question, entries)
        raw_response, token_usage = await self._llm_answer(prompt)
        parsed = parse_faq_answer_response(raw_response, {entry.faq_id for entry in entries})
        if not parsed:
            logger.info("[FAQ-Answer] FAQ context did not fully answer: '%s'", question[:80])
            return None

        faq_by_id = {str(getattr(faq, "id", "")): faq for faq in faq_docs}
        matched_faqs: list[Any] = []
        for faq_id in parsed["faq_ids"]:
            matched_faq = faq_by_id.get(faq_id)
            if not matched_faq or not getattr(matched_faq, "is_active", True):
                return None
            matched_faqs.append(matched_faq)

        logger.info(
            "[FAQ-Answer] LLM answered from FAQ ids=%s",
            parsed["faq_ids"],
        )
        if increment_view_count:
            for faq_id in parsed["faq_ids"]:
                asyncio.create_task(self._faq_repo.increment_view_count(faq_id))

        return FaqAnswerResult(
            answer_markdown=parsed["answer_markdown"],
            matched_faqs=matched_faqs,
            token_usage=token_usage,
        )

    @staticmethod
    def _build_entries(faq_docs: list[Any]) -> list[FaqAnswerEntry]:
        entries: list[FaqAnswerEntry] = []
        for faq in faq_docs:
            meta = getattr(faq, "metadata_filter", None)
            enrollment_year = meta.enrollment_year.model_dump() if meta and meta.enrollment_year else None
            academic_year = meta.academic_year.model_dump() if meta and meta.academic_year else None
            entries.append(FaqAnswerEntry(
                faq_id=str(getattr(faq, "id", "")),
                question=getattr(faq, "question", "") or "",
                answer_markdown=getattr(faq, "answer_markdown", "") or "",
                enrollment_year=enrollment_year,
                academic_year=academic_year,
            ))
        return entries


_faq_answer_service_instance: FaqAnswerService | None = None


def get_faq_answer_service() -> FaqAnswerService:
    global _faq_answer_service_instance
    if _faq_answer_service_instance is None:
        _faq_answer_service_instance = FaqAnswerService()
    return _faq_answer_service_instance
