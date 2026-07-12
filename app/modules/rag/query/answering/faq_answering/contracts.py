from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


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
            "type": "faq_answer",
            "answered": True,
            "faq_ids": [str(getattr(faq, "id", "")) for faq in self.matched_faqs],
            "questions": [getattr(faq, "question", "") for faq in self.matched_faqs],
        }
