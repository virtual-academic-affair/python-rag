from typing import Optional
from pydantic import Field
from app.core.base_schema import BaseSchema


class OcrReviewResponse(BaseSchema):
    file_id: str
    status: str
    markdown: str
    ocr_page_count: Optional[int] = None
    ocr_completed_at: Optional[str] = None
    last_processing_error: Optional[str] = None


class OcrReviewUpdateRequest(BaseSchema):
    markdown: str = Field(..., min_length=1, description="Markdown draft content")
