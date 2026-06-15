from typing import Optional
from pydantic import Field
from app.core.base_schema import BaseSchema

class FormUpdateRequest(BaseSchema):
    document_type: Optional[str] = Field(None, min_length=1, max_length=255)
    content_link: Optional[str] = Field(None, min_length=1, max_length=20000)
    notes: Optional[str] = Field(None, max_length=50000)
