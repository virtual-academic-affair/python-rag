from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict, Field
from pydantic.alias_generators import to_camel

from app.core.base_schema import BaseSchema
from app.modules.corpus.contracts import CorpusRole
from app.modules.metadata.dtos import UnifiedFilterResponse
from app.modules.rag.query.contracts import RagQueryAnalysis, RagQueryResult
from app.modules.rag.query.dtos.source_citation import SourceCitation
from app.modules.rag.query.dtos.token_usage import TokenUsage


class RagChatPreviewRequest(BaseSchema):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, serialize_by_alias=True, extra="forbid")

    question: str = Field(min_length=1, max_length=2000)
    role: CorpusRole = "student"
    enrollment_year: int | None = Field(default=None, ge=0, le=9999)


class RagQueryAnalysisResponse(BaseSchema):
    original_question: str
    effective_question: str
    needs_rag: bool
    metadata_filter: UnifiedFilterResponse | None = None

    @classmethod
    def from_domain(cls, analysis: RagQueryAnalysis | None) -> "RagQueryAnalysisResponse | None":
        if analysis is None:
            return None
        return cls(
            original_question=analysis.original_question,
            effective_question=analysis.effective_question,
            needs_rag=analysis.needs_rag,
            metadata_filter=UnifiedFilterResponse.from_mapping(analysis.metadata_filter),
        )


class RagPreviewFileCandidate(BaseSchema):
    file_id: str
    file_name: str


class RagPreviewFaq(BaseSchema):
    faq_id: str
    question: str


class RagPreviewStep(BaseSchema):
    type: str
    content: str


class RagChatPreviewResponse(BaseSchema):
    analysis: RagQueryAnalysisResponse | None = None
    answer: str
    source: Literal["llm", "faq", "bypass"]
    role: CorpusRole
    is_direct_reply: bool = False
    max_turns_reached: bool = False
    file_candidates: list[RagPreviewFileCandidate] = Field(default_factory=list)
    faqs: list[RagPreviewFaq] = Field(default_factory=list)
    sources: list[SourceCitation] = Field(default_factory=list)
    steps: list[RagPreviewStep] = Field(default_factory=list)
    token_usage: TokenUsage | None = None

    @classmethod
    def from_result(
        cls,
        result: RagQueryResult,
        *,
        role: CorpusRole,
        steps: list[dict],
    ) -> "RagChatPreviewResponse":
        return cls(
            analysis=RagQueryAnalysisResponse.from_domain(result.analysis),
            answer=result.answer_markdown,
            source=result.source,
            role=role,
            is_direct_reply=result.is_direct_reply,
            max_turns_reached=result.max_turns_reached,
            file_candidates=[RagPreviewFileCandidate(file_id=item["file_id"], file_name=item["file_name"]) for item in result.candidate_files],
            faqs=[RagPreviewFaq(faq_id=str(faq.id), question=faq.question) for faq in result.faq_docs],
            sources=[SourceCitation.model_validate(source) for source in result.sources],
            steps=[RagPreviewStep(type=item.get("type", ""), content=item.get("content", "")) for item in steps],
            token_usage=TokenUsage.from_mapping(result.token_usage),
        )
