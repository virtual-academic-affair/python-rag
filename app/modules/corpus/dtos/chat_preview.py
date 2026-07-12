from __future__ import annotations

from typing import Any, Optional

from pydantic import Field

from app.core.base_schema import BaseSchema
from app.modules.corpus.contracts import CorpusRole
from app.modules.corpus.dtos.traverse_corpus import CorpusMetadataFilterResponse
from app.modules.rag.query.dtos import SourceCitation


class ChatPreviewRequest(BaseSchema):
    question: str
    role: CorpusRole = "student"
    enrollment_year: Optional[int] = None


class ChatPreviewFileCandidate(BaseSchema):
    file_id: str
    file_name: str


class ChatPreviewFaq(BaseSchema):
    question: str
    is_active: bool


class ChatPreviewQueryAnalysis(BaseSchema):
    type: str
    original_question: str
    effective_question: str
    needs_rag: bool = True
    metadata_filter: CorpusMetadataFilterResponse | None = None

    @classmethod
    def from_step(cls, step: dict[str, Any] | None) -> "ChatPreviewQueryAnalysis | None":
        if not step:
            return None
        return cls(
            type=step.get("type") or "query_analysis",
            original_question=step.get("original_question") or "",
            effective_question=step.get("effective_question") or "",
            needs_rag=bool(step.get("needs_rag", True)),
            metadata_filter=CorpusMetadataFilterResponse.from_filter(step.get("metadata_filter")),
        )


class ChatPreviewStep(BaseSchema):
    type: str
    content: str


class ChatPreviewPipelineResult(BaseSchema):
    source: str
    max_turns_reached: bool
    role_used_for_filtering: CorpusRole
    file_candidates: list[ChatPreviewFileCandidate] = Field(default_factory=list)
    faq_docs: list[ChatPreviewFaq] = Field(default_factory=list)
    sources: list[SourceCitation] = Field(default_factory=list)
    steps: list[ChatPreviewStep] = Field(default_factory=list)


class ChatPreviewResponse(BaseSchema):
    query_analysis: ChatPreviewQueryAnalysis | None = None
    pipeline_result: ChatPreviewPipelineResult
