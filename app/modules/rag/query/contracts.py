from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


QueryMode = Literal["chat", "email"]
AnalyzerMode = Literal["chat", "email", "none"]
RagQuerySource = Literal["llm", "faq", "bypass"]


@dataclass
class RagQueryInput:
    mode: QueryMode
    question: str
    user_role: str
    user_name: str = ""
    enrollment_year: int | None = None
    metadata_filter: dict[str, Any] | None = None
    chat_history: list[Any] = field(default_factory=list)
    email_subject: str | None = None
    email_content: str | None = None


@dataclass
class RagQueryBehavior:
    mode: QueryMode
    analyzer_mode: AnalyzerMode
    allow_direct_reply: bool
    allow_enrollment_fallback: bool
    include_reasoning: bool
    system_prompt: str
    faq_system_prompt: str
    no_candidate_message: str


@dataclass
class RagQueryAnalysis:
    original_question: str
    effective_question: str
    needs_rag: bool
    metadata_filter: dict[str, Any]
    usage: dict[str, Any] | None = None
    inquiry_types: list[str] = field(default_factory=list)

    def as_step(self) -> dict[str, Any]:
        return {
            "type": "query_analysis",
            "original_question": self.original_question,
            "effective_question": self.effective_question,
            "needs_rag": self.needs_rag,
            "metadata_filter": self.metadata_filter,
            "inquiry_types": self.inquiry_types,
        }


@dataclass
class RagQueryResult:
    answer_markdown: str
    source: RagQuerySource
    sources: list[dict[str, Any]]
    steps: list[dict[str, Any]]
    token_usage: dict[str, Any] | None
    candidate_files: list[dict[str, Any]]
    faq_docs: list[Any]
    used_faq_docs: list[Any] = field(default_factory=list)
    max_turns_reached: bool = False
    analysis: RagQueryAnalysis | None = None
    is_direct_reply: bool = False
