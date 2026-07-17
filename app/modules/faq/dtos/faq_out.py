from typing import Optional
from pydantic import Field
from app.core.base_schema import BaseSchema
from app.modules.faq.models.faq import FaqDocument
from app.modules.metadata.dtos.metadata_out import FaqMetadataResponse
from app.modules.metadata.models.value_objects import FaqMetadata

class FaqResponse(BaseSchema):
    id: str = Field(..., alias="faqId")
    question: str
    answer_rich_text: str
    lecturer_only: bool = False
    metadata_filter: FaqMetadataResponse
    view_count: int
    source: str
    created_at: str
    updated_at: str
    deleted_at: Optional[str] = None
    deleted_by: Optional[str] = None

    @classmethod
    def from_document(cls, doc: FaqDocument) -> 'FaqResponse':
        raw_meta = doc.metadata_filter or FaqMetadata()
        try:
            if isinstance(raw_meta, dict):
                if "enrollment_year" in raw_meta or "enrollmentYear" in raw_meta:
                    meta_model = FaqMetadata(**raw_meta)
                else:
                    meta_model = FaqMetadata()
            else:
                meta_model = raw_meta
        except Exception:
            meta_model = FaqMetadata()

        return cls(
            id=str(doc.id),
            question=doc.question,
            answer_rich_text=doc.answer_rich_text or "",
            lecturer_only=bool(getattr(doc, "lecturer_only", False)),
            metadata_filter=FaqMetadataResponse.from_model(meta_model),
            view_count=doc.view_count,
            source=doc.source,
            created_at=doc.created_at.isoformat() if doc.created_at else "",
            updated_at=doc.updated_at.isoformat() if doc.updated_at else "",
            deleted_at=doc.deleted_at.isoformat() if getattr(doc, "deleted_at", None) else None,
            deleted_by=getattr(doc, "deleted_by", None),
        )
