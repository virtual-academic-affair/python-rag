"""
Schemas for the FAQ Module.
"""
from typing import List, Optional, Literal
from pydantic import BaseModel, Field, ConfigDict
from pydantic.alias_generators import to_camel


class BaseSchema(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        serialize_by_alias=True,
    )


class FaqMetadataFilter(BaseSchema):
    academic_year: List[str] = Field(default_factory=list)
    cohort: List[str] = Field(default_factory=list)


class FaqCreateRequest(BaseSchema):
    question: str = Field(..., min_length=5, max_length=500)
    answer_rich_text: str = Field(..., min_length=5, max_length=50000)
    metadata_filter: FaqMetadataFilter = Field(default_factory=FaqMetadataFilter)


class FaqUpdateRequest(BaseSchema):
    question: Optional[str] = Field(None, min_length=5, max_length=500)
    answer_rich_text: Optional[str] = Field(None, min_length=5, max_length=50000)
    metadata_filter: Optional[FaqMetadataFilter] = None
    is_active: Optional[bool] = None


class FaqResponse(BaseSchema):
    id: str = Field(..., alias="faqId")
    question: str
    answer_rich_text: str
    metadata_filter: FaqMetadataFilter
    is_active: bool
    view_count: int
    source: str
    created_at: str
    updated_at: str

    @classmethod
    def from_mongo(cls, doc: dict) -> 'FaqResponse':
        return cls(
            id=str(doc.get("_id", doc.get("id"))),
            question=doc.get("question", ""),
            answer_rich_text=doc.get("answer_rich_text", ""),
            metadata_filter=FaqMetadataFilter(**(doc.get("metadata_filter") or {})),
            is_active=doc.get("is_active", True),
            view_count=doc.get("view_count", 0),
            source=doc.get("source", "manual"),
            created_at=doc.get("created_at").isoformat() if doc.get("created_at") else "",
            updated_at=doc.get("updated_at").isoformat() if doc.get("updated_at") else ""
        )


class FaqListResponse(BaseSchema):
    items: List[FaqResponse]
    total: int
    page: int
    limit: int


class FaqCandidateResponse(BaseSchema):
    id: str = Field(..., alias="candidateId")
    question: str
    answer_draft_rich_text: str
    metadata_filter_suggestion: FaqMetadataFilter
    source_type: str
    similar_count: int
    status: str
    synthesis_batch_id: str
    created_at: str

    @classmethod
    def from_mongo(cls, doc: dict) -> 'FaqCandidateResponse':
        return cls(
            id=str(doc.get("_id", doc.get("id"))),
            question=doc.get("question", ""),
            answer_draft_rich_text=doc.get("answer_draft_rich_text", ""),
            metadata_filter_suggestion=FaqMetadataFilter(**(doc.get("metadata_filter_suggestion") or {})),
            source_type=doc.get("source_type", ""),
            similar_count=doc.get("similar_count", 0),
            status=doc.get("status", "pending"),
            synthesis_batch_id=doc.get("synthesis_batch_id", ""),
            created_at=doc.get("created_at").isoformat() if doc.get("created_at") else ""
        )


class FaqCandidateListResponse(BaseSchema):
    items: List[FaqCandidateResponse]
    total: int
    page: int
    limit: int


class FaqReviewRequest(BaseSchema):
    action: Literal["approve", "reject"] = Field(..., description="Action to take on the candidate")
    question_override: Optional[str] = Field(None, description="Modify the question before approving")
    answer_rich_text_override: Optional[str] = Field(None, description="Modify the answer before approving")
    metadata_filter_override: Optional[FaqMetadataFilter] = Field(None, description="Modify the metadata filters before approving")
    note: Optional[str] = None


class FaqSynthesisRequest(BaseSchema):
    date_from: Optional[str] = Field(None, description="ISO format date. Default is now - LOOKBACK_DAYS")
    date_to: Optional[str] = Field(None, description="ISO format date. Default is now")
    sources: List[str] = Field(default_factory=lambda: ["chat", "inquiry_email"])


class FaqSynthesisResponse(BaseSchema):
    batch_id: str
    candidates_created: int
    total_logs_processed: int
    clusters_found: int
    failed_clusters: int


class FaqMatchRequest(BaseSchema):
    question: str
    metadata_filter: FaqMetadataFilter = Field(default_factory=FaqMetadataFilter)
    threshold: Optional[float] = None


# --- Bulk Import & Create Schemas ---

class FaqImportRow(BaseSchema):
    row_index: int
    question: str
    answer_rich_text: str
    answer_markdown: str
    metadata: FaqMetadataFilter
    is_valid: bool
    error: Optional[str] = None


class FaqImportPreviewResponse(BaseSchema):
    total_rows: int
    valid_rows: int
    invalid_rows: int
    rows: List[FaqImportRow]


class FaqBulkCreateItem(BaseSchema):
    question: str = Field(..., min_length=5, max_length=500)
    answer_rich_text: str = Field(..., min_length=5, max_length=50000)
    metadata_filter: FaqMetadataFilter = Field(default_factory=FaqMetadataFilter)


class FaqBulkCreateRequest(BaseSchema):
    items: List[FaqBulkCreateItem]
    skip_duplicates: bool = True


class FaqBulkCreateError(BaseSchema):
    row_index: Optional[int] = None
    question: str
    error: str


class FaqBulkCreateResponse(BaseSchema):
    total: int
    created: int
    skipped: int
    failed: int
    errors: List[FaqBulkCreateError]
