from typing import Optional, List
from pydantic import Field
from app.core.base_schema import BaseSchema
from app.modules.forms.dtos.form_out import FormResponse

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
    created: Optional[int] = None
