from typing import Optional
from pydantic import Field
from app.core.base_schema import BaseSchema
from app.modules.metadata.dtos.metadata_out import FaqMetadataResponse

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
        from app.modules.metadata.models.value_objects import FaqMetadata
        raw_meta = doc.get("metadata_filter") or {}
        try:
            if isinstance(raw_meta, dict):
                if "enrollment_year" in raw_meta or "enrollmentYear" in raw_meta:
                    meta_model = FaqMetadata(**raw_meta)
                else:
                    meta_model = FaqMetadata()
            else:
                meta_model = FaqMetadata()
        except Exception:
            meta_model = FaqMetadata()

        created_val = doc.get("created_at")
        updated_val = doc.get("updated_at")
        created_str = created_val.isoformat() if created_val and not isinstance(created_val, str) else str(created_val or "")
        updated_str = updated_val.isoformat() if updated_val and not isinstance(updated_val, str) else str(updated_val or "")

        return cls(
            id=str(doc.get("_id", doc.get("id"))),
            question=doc.get("question", ""),
            answer_rich_text=doc.get("answer_rich_text", ""),
            metadata_filter=FaqMetadataResponse.from_model(meta_model),
            is_active=doc.get("is_active", True),
            view_count=doc.get("view_count", 0),
            source=doc.get("source", "manual"),
            created_at=created_str,
            updated_at=updated_str
        )

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
        from app.modules.metadata.models.value_objects import FaqMetadata
        raw_meta = doc.get("metadata_filter_suggestion") or {}
        try:
            meta_model = FaqMetadata(**raw_meta)
        except Exception:
            meta_model = FaqMetadata()

        created_val = doc.get("created_at")
        created_str = created_val.isoformat() if created_val and not isinstance(created_val, str) else str(created_val or "")

        return cls(
            id=str(doc.get("_id", doc.get("id"))),
            question=doc.get("question", ""),
            answer_draft_rich_text=doc.get("answer_draft_rich_text", ""),
            metadata_filter_suggestion=FaqMetadataResponse.from_model(meta_model),
            source_type=doc.get("source_type", ""),
            similar_count=doc.get("similar_count", 0),
            status=doc.get("status", "pending"),
            synthesis_batch_id=doc.get("synthesis_batch_id", ""),
            created_at=created_str
        )
