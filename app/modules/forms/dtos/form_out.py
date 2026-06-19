from typing import Optional
from pydantic import Field
from app.core.base_schema import BaseSchema
from app.modules.forms.models.form import FormDocument

class FormResponse(BaseSchema):
    id: str = Field(...)
    document_type: str
    content_link: str
    notes: Optional[str]
    created_at: str
    updated_at: str

    @classmethod
    def from_document(cls, doc: FormDocument) -> 'FormResponse':
        return cls(
            id=str(doc.id),
            document_type=doc.documentType,
            content_link=doc.contentLink,
            notes=doc.notes,
            created_at=doc.created_at.isoformat() if doc.created_at else "",
            updated_at=doc.updated_at.isoformat() if doc.updated_at else ""
        )
