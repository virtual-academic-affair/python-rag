from typing import Optional, Literal
from pydantic import Field
from app.core.base_schema import BaseSchema
from app.modules.metadata.dtos.update_metadata import FaqMetadataSchema

class FaqUpdateRequest(BaseSchema):
    question: Optional[str] = Field(None, min_length=5, max_length=500)
    answer_rich_text: Optional[str] = Field(None, min_length=5, max_length=50000)
    metadata_filter: Optional[FaqMetadataSchema] = None
    is_active: Optional[bool] = None

class FaqReviewRequest(BaseSchema):
    action: Literal["approve", "reject"] = Field(..., description="Action to take on the candidate")
    question_override: Optional[str] = Field(None, description="Modify the question before approving")
    answer_rich_text_override: Optional[str] = Field(None, description="Modify the answer before approving")
    metadata_filter_override: Optional[FaqMetadataSchema] = Field(None, description="Modify the metadata filters before approving")
    note: Optional[str] = None
