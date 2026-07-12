from typing import List, Optional
from pydantic import Field
from app.core.base_schema import BaseSchema
from app.modules.metadata.dtos.update_metadata import FaqMetadataCreateSchema

class FaqCreateRequest(BaseSchema):
    question: str = Field(..., min_length=5, max_length=500)
    answer_rich_text: str = Field(..., min_length=5, max_length=50000)
    lecturer_only: bool = Field(False, description="Nếu True, chỉ admin/lecture mới xem được")
    metadata_filter: FaqMetadataCreateSchema = Field(default_factory=FaqMetadataCreateSchema)

class FaqBulkCreateItem(BaseSchema):
    question: str = Field(..., min_length=5, max_length=500)
    answer_rich_text: str = Field(..., min_length=5, max_length=50000)
    lecturer_only: bool = Field(False, description="Nếu True, chỉ admin/lecture mới xem được")
    metadata_filter: FaqMetadataCreateSchema = Field(default_factory=FaqMetadataCreateSchema)

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
