"""
Schemas for the FAQ Module.
"""
from typing import List, Optional, Literal
from pydantic import Field
from app.core.schemas import BaseSchema


from app.modules.metadata.schemas import FaqMetadataSchema, FaqMetadataResponse


class FaqCreateRequest(BaseSchema):
    question: str = Field(..., min_length=5, max_length=500)
    answer_rich_text: str = Field(..., min_length=5, max_length=50000)
    metadata_filter: FaqMetadataSchema = Field(default_factory=FaqMetadataSchema)


class FaqUpdateRequest(BaseSchema):
    question: Optional[str] = Field(None, min_length=5, max_length=500)
    answer_rich_text: Optional[str] = Field(None, min_length=5, max_length=50000)
    metadata_filter: Optional[FaqMetadataSchema] = None
    is_active: Optional[bool] = None


class FaqResponse(BaseSchema):
    id: str = Field(..., alias="faqId")
    question: str
    answer_rich_text: str
    metadata_filter: FaqMetadataResponse
    is_active: bool
    view_count: int
    source: str
    created_at: str
    updated_at: str

    @classmethod
    def from_mongo(cls, doc: dict) -> 'FaqResponse':
        from app.modules.metadata.models import FaqMetadata
        raw_meta = doc.get("metadata_filter") or {}
        # Ensure we can handle both old list-based and new range-based metadata during transition if needed
        # but here we assume new schema as per refactor.
        try:
            if isinstance(raw_meta, dict):
                # If it has enrollment_year key, it's the new model
                if "enrollment_year" in raw_meta or "enrollmentYear" in raw_meta:
                    meta_model = FaqMetadata(**raw_meta)
                else:
                    # Legacy or empty
                    meta_model = FaqMetadata()
            else:
                meta_model = FaqMetadata()
        except Exception:
            meta_model = FaqMetadata()

        return cls(
            id=str(doc.get("_id", doc.get("id"))),
            question=doc.get("question", ""),
            answer_rich_text=doc.get("answer_rich_text", ""),
            metadata_filter=FaqMetadataResponse.from_model(meta_model),
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
    metadata_filter_suggestion: FaqMetadataResponse
    source_type: str
    similar_count: int
    status: str
    synthesis_batch_id: str
    created_at: str

    @classmethod
    def from_mongo(cls, doc: dict) -> 'FaqCandidateResponse':
        from app.modules.metadata.models import FaqMetadata
        raw_meta = doc.get("metadata_filter_suggestion") or {}
        try:
            meta_model = FaqMetadata(**raw_meta)
        except Exception:
            meta_model = FaqMetadata()

        return cls(
            id=str(doc.get("_id", doc.get("id"))),
            question=doc.get("question", ""),
            answer_draft_rich_text=doc.get("answer_draft_rich_text", ""),
            metadata_filter_suggestion=FaqMetadataResponse.from_model(meta_model),
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
    metadata_filter_override: Optional[FaqMetadataSchema] = Field(None, description="Modify the metadata filters before approving")
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
    metadata_filter: FaqMetadataSchema = Field(default_factory=FaqMetadataSchema)
    threshold: Optional[float] = None


# --- Bulk Import & Create Schemas ---

class FaqImportRow(BaseSchema):
    row_index: int
    question: str
    answer_rich_text: str
    answer_markdown: str
    metadata: FaqMetadataResponse
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
    metadata_filter: FaqMetadataSchema = Field(default_factory=FaqMetadataSchema)


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

