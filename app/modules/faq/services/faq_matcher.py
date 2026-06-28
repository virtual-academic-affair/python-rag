"""Vectorless FAQ matcher — replaces Qdrant cosine similarity search for FAQ pre-check.

Pure stdlib so it is testable in a bare venv without Qdrant/Beanie.

The async class ``FaqMatcher`` takes its LLM call as a dependency so it can be
tested without a network round-trip (inject a fake callable in tests).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Coroutine, List, Optional


@dataclass
class FaqMatchEntry:
    """One row in the FAQ catalog presented to the matcher LLM."""

    faq_id: str
    question: str
    enrollment_year: Optional[dict] = None
    academic_year: Optional[dict] = None


def _fmt_year(yr: Optional[dict]) -> str:
    if not yr:
        return "mọi khóa"
    f, t = yr.get("from_year"), yr.get("to_year")
    if f in (None, 0) and t in (None, 9999):
        return "mọi khóa"
    if f == t:
        return str(f)
    return f"{f}-{t}"


def render_faq_catalog(entries: List[FaqMatchEntry]) -> str:
    """Render the FAQ list into the text block fed to the matcher LLM."""
    lines = []
    for i, e in enumerate(entries, 1):
        lines.append(
            f"[{i}] {e.question}\n"
            f"    Khóa: {_fmt_year(e.enrollment_year)} | Năm học: {_fmt_year(e.academic_year)}"
        )
    return "\n\n".join(lines)


def _loads_tolerant(raw_text: str) -> Any:
    """Parse JSON, tolerating markdown code fences the LLM may wrap it in."""
    text = (raw_text or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1] if "\n" in text else ""
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return None


def parse_match_response(raw_text: str, num_entries: int) -> Optional[dict]:
    """Parse the matcher LLM JSON to a single validated selection or ``None``.

    Returns ``None`` when the LLM explicitly says no match (``"match": null``)
    or when the response is malformed / the index is out of range.
    """
    data = _loads_tolerant(raw_text)
    if not isinstance(data, dict):
        return None

    match = data.get("match")
    if match is None:
        return None  # LLM explicitly said no match

    if not isinstance(match, dict):
        return None

    idx = match.get("index")
    if not isinstance(idx, int) or isinstance(idx, bool):
        return None
    if not (1 <= idx <= num_entries):
        return None

    return {
        "index": idx,
        "score": match.get("score"),
        "reason": match.get("reason") or "",
    }


MATCH_SYSTEM_PROMPT = """Bạn là bộ khớp câu hỏi FAQ của hệ thống tư vấn Phòng Giáo vụ.

Cho một CÂU HỎI của sinh viên và một DANH SÁCH câu hỏi FAQ (kèm thông tin khóa/năm học),
hãy xác định xem FAQ nào (nếu có) là câu trả lời TRỰC TIẾP cho câu hỏi đó.

Nguyên tắc:
- Chỉ chọn FAQ khi câu hỏi của sinh viên về cùng một chủ đề và sẽ được trả lời ĐẦY ĐỦ bởi FAQ.
  Không chọn khi câu hỏi chỉ liên quan mờ nhạt hoặc rộng hơn phạm vi FAQ.
- Ưu tiên khớp về KHÓA/NĂM HỌC nếu câu hỏi có đề cập.
- Nếu KHÔNG có FAQ nào phù hợp, trả về "match": null.
- Chỉ chọn MỘT FAQ tốt nhất.

CHỈ trả về JSON đúng schema (không thêm giải thích ngoài JSON):
{{
  "match": {{
    "index": <số thứ tự FAQ>,
    "score": <0.0-1.0>,
    "reason": "<lý do ngắn gọn tiếng Việt>"
  }}
}}
hoặc nếu không có kết quả phù hợp: {{"match": null}}
"""

LLMCall = Callable[[str], Coroutine[Any, Any, str]]


class FaqMatcher:
    """Finds the best matching FAQ for a question via a single LLM pass.

    The LLM call is injected so this class is testable without a network
    round-trip.
    """

    def __init__(self, llm_call: LLMCall):
        self._llm = llm_call

    def build_prompt(self, question: str, entries: List[FaqMatchEntry]) -> str:
        catalog = render_faq_catalog(entries)
        return (
            MATCH_SYSTEM_PROMPT
            + f'\n\nCÂU HỎI: "{question}"\n\nDANH SÁCH FAQ:\n{catalog}\n\nTrả về JSON:'
        )

    async def match(
        self, question: str, entries: List[FaqMatchEntry]
    ) -> Optional[dict]:
        """Return ``{"entry": FaqMatchEntry, "score": float, "reason": str}`` or ``None``."""
        if not entries:
            return None
        prompt = self.build_prompt(question, entries)
        raw = await self._llm(prompt)
        sel = parse_match_response(raw, len(entries))
        if not sel:
            return None
        return {
            "entry": entries[sel["index"] - 1],
            "score": sel["score"],
            "reason": sel["reason"],
        }
