from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, ConfigDict
from pydantic.alias_generators import to_camel

class BaseSchema(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        serialize_by_alias=True,
    )

class FormCreateRequest(BaseSchema):
    document_type: str = Field(..., min_length=1, max_length=255)
    content_link: str = Field(..., min_length=1, max_length=20000)
    notes: Optional[str] = Field(None, max_length=50000)

class FormUpdateRequest(BaseSchema):
    document_type: Optional[str] = Field(None, min_length=1, max_length=255)
    content_link: Optional[str] = Field(None, min_length=1, max_length=20000)
    notes: Optional[str] = Field(None, max_length=50000)

class FormResponse(BaseSchema):
    id: str = Field(...)
    document_type: str
    content_link: str
    notes: Optional[str]
    created_at: str
    updated_at: str

    @classmethod
    def from_mongo(cls, doc: dict) -> 'FormResponse':
        return cls(
            id=str(doc.get("_id", doc.get("id"))),
            document_type=doc.get("documentType", ""),
            content_link=doc.get("contentLink", ""),
            notes=doc.get("notes"),
            created_at=doc.get("createdAt").isoformat() if doc.get("createdAt") else "",
            updated_at=doc.get("updatedAt").isoformat() if doc.get("updatedAt") else ""
        )

class Pagination(BaseSchema):
    total: int
    current_page: int
    limit: int
    total_pages: int

class FormListResponse(BaseSchema):
    items: List[FormResponse]
    pagination: Pagination

class FormImportRow(BaseSchema):
    document_type: str
    content_link: str
    notes: Optional[str] = None
    is_valid: bool = True
    error: Optional[str] = None

class FormImportPreviewResponse(BaseSchema):
    rows: List[FormImportRow]
    total_previewed: int

class FormBulkImportRequest(BaseSchema):
    start_row: Optional[str] = None
    document_type_col: Optional[str] = None
    content_link_col: Optional[str] = None
    notes_col: Optional[str] = None

class FormBulkCreateResponse(BaseSchema):
    message: str
    count: int
