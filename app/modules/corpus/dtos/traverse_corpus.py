from __future__ import annotations

from typing import Any, Literal

from pydantic import ConfigDict, Field
from pydantic.alias_generators import to_camel

from app.core.base_schema import BaseSchema
from app.modules.corpus.contracts import CorpusRole, TraversalResult
from app.modules.metadata.dtos import UnifiedFilterResponse, UnifiedFilterSchema
from app.modules.rag.query.dtos import TokenUsage


class CorpusTraversalRequest(BaseSchema):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, serialize_by_alias=True, extra="forbid")

    question: str = Field(min_length=1, max_length=2000)
    role: CorpusRole = "student"
    metadata_filter: UnifiedFilterSchema | None = None

    def normalized_metadata_filter(self) -> dict[str, Any]:
        return self.metadata_filter.model_dump(by_alias=False, exclude_none=True) if self.metadata_filter else {}


class TraversalFileCandidateResponse(BaseSchema):
    file_id: str
    node_key: str | None = None
    node_title: str | None = None


class TraversalFaqCandidateResponse(BaseSchema):
    faq_id: str
    node_key: str | None = None
    node_title: str | None = None


class TraversalTopicSelectionResponse(BaseSchema):
    node_key: str
    node_title: str | None = None
    scope: Literal["direct", "subtree"]


class CorpusPrefilterResponse(BaseSchema):
    allowed_file_count: int = 0
    allowed_faq_count: int = 0

    @classmethod
    def from_trace(cls, prefilter: dict[str, Any] | None) -> "CorpusPrefilterResponse | None":
        if not prefilter:
            return None
        return cls(
            allowed_file_count=int(prefilter.get("allowed_file_count") or 0),
            allowed_faq_count=int(prefilter.get("allowed_faq_count") or 0),
        )


class CorpusTraversalResponse(BaseSchema):
    query: str
    role: CorpusRole
    metadata_filter: UnifiedFilterResponse | None = None
    prefilter: CorpusPrefilterResponse | None = None
    status: Literal["selected", "no_match"] = "no_match"
    selected_topics: list[TraversalTopicSelectionResponse] = Field(default_factory=list)
    expanded_node_keys: list[str] = Field(default_factory=list)
    inspected_node_keys: list[str] = Field(default_factory=list)
    termination_reason: str = ""
    turn_count: int = 0
    token_usage: TokenUsage | None = None
    file_candidates: list[TraversalFileCandidateResponse] = Field(default_factory=list)
    faq_candidates: list[TraversalFaqCandidateResponse] = Field(default_factory=list)

    @classmethod
    def from_result(
        cls,
        request: CorpusTraversalRequest,
        result: TraversalResult,
    ) -> "CorpusTraversalResponse":
        return cls(
            query=request.question,
            role=request.role,
            metadata_filter=UnifiedFilterResponse.from_mapping(request.normalized_metadata_filter()),
            prefilter=CorpusPrefilterResponse.from_trace(result.prefilter),
            status=result.status,
            selected_topics=[
                TraversalTopicSelectionResponse(
                    node_key=item.node_key, node_title=item.node_title, scope=item.scope
                )
                for item in result.selected_topics
            ],
            expanded_node_keys=result.expanded_node_keys,
            inspected_node_keys=result.inspected_node_keys,
            termination_reason=result.termination_reason,
            turn_count=result.turn_count,
            token_usage=TokenUsage.from_mapping(result.token_usage),
            file_candidates=[
                TraversalFileCandidateResponse(
                    file_id=item.file_id, node_key=item.node_key, node_title=item.node_title
                )
                for item in result.file_candidates
            ],
            faq_candidates=[
                TraversalFaqCandidateResponse(
                    faq_id=item.faq_id, node_key=item.node_key, node_title=item.node_title
                )
                for item in result.faq_candidates
            ],
        )
