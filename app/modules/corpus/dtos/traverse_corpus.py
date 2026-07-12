from __future__ import annotations

from typing import Any, Optional

from pydantic import Field

from app.core.base_schema import BaseSchema
from app.modules.corpus.contracts import CorpusRole
from app.modules.metadata.dtos.metadata_out import YearRangeResponse
from app.modules.metadata.dtos.update_metadata import RelaxedUnifiedFilterSchema, YearRangeSchema


class TraverseRequest(BaseSchema):
    question: str
    role: CorpusRole = "student"
    metadata_filter: RelaxedUnifiedFilterSchema | None = None
    enrollment_year: Optional[int] = None
    academic_year: Optional[int | YearRangeSchema] = None

    def normalized_metadata_filter(self) -> dict[str, Any]:
        metadata_filter = (
            self.metadata_filter.model_dump(by_alias=False, exclude_none=True)
            if self.metadata_filter
            else {}
        )
        if self.enrollment_year and "enrollment_year" not in metadata_filter:
            metadata_filter["enrollment_year"] = {
                "from_year": self.enrollment_year,
                "to_year": self.enrollment_year,
            }
        if self.academic_year and "academic_year" not in metadata_filter:
            if isinstance(self.academic_year, YearRangeSchema):
                metadata_filter["academic_year"] = self.academic_year.model_dump(by_alias=False)
            else:
                metadata_filter["academic_year"] = {
                    "from_year": self.academic_year,
                    "to_year": self.academic_year,
                }
        return metadata_filter


class FileCandidateResponse(BaseSchema):
    file_id: str
    node_key: str | None = None
    node_title: str | None = None


class FaqCandidateResponse(BaseSchema):
    faq_id: str
    node_key: str | None = None
    node_title: str | None = None


class TopicSelectionResponse(BaseSchema):
    node_key: str
    node_title: str | None = None
    scope: str


class TraversalTokenUsageResponse(BaseSchema):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class CorpusMetadataFilterResponse(BaseSchema):
    enrollment_year: YearRangeResponse | None = None
    academic_year: YearRangeResponse | None = None
    type: list[str] | None = None

    @classmethod
    def from_filter(cls, metadata_filter: dict[str, Any] | None) -> "CorpusMetadataFilterResponse | None":
        if not metadata_filter:
            return None
        return cls(
            enrollment_year=_year_range_from_dict(metadata_filter.get("enrollment_year")),
            academic_year=_year_range_from_dict(metadata_filter.get("academic_year")),
            type=metadata_filter.get("type"),
        )


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


def _year_range_from_dict(value: Any) -> YearRangeResponse | None:
    if not isinstance(value, dict):
        return None
    return YearRangeResponse(
        from_year=int(value.get("from_year") if value.get("from_year") is not None else value.get("fromYear", 0)),
        to_year=int(value.get("to_year") if value.get("to_year") is not None else value.get("toYear", 9999)),
    )


class TraverseResponse(BaseSchema):
    query: str
    role: CorpusRole
    metadata_filter: CorpusMetadataFilterResponse | None = None
    prefilter: CorpusPrefilterResponse | None = None
    traversal_node_keys: list[str] = Field(default_factory=list)
    status: str = "no_match"
    selected_topics: list[TopicSelectionResponse] = Field(default_factory=list)
    expanded_node_keys: list[str] = Field(default_factory=list)
    inspected_node_keys: list[str] = Field(default_factory=list)
    termination_reason: str = ""
    turn_count: int = 0
    token_usage: TraversalTokenUsageResponse | None = None
    file_candidates: list[FileCandidateResponse] = Field(default_factory=list)
    faq_candidates: list[FaqCandidateResponse] = Field(default_factory=list)
    total_file_candidates: int = 0
    total_faq_candidates: int = 0
