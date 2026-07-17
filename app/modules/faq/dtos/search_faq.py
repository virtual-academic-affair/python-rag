from typing import List
from pydantic import Field
from app.core.base_schema import BaseSchema
from app.modules.metadata.dtos.update_metadata import FaqMetadataSchema

class FaqMatchRequest(BaseSchema):
    question: str
    metadata_filter: FaqMetadataSchema = Field(default_factory=FaqMetadataSchema)

class FaqMatchResponse(BaseSchema):
    answer_markdown: str
    faq_ids: List[str]
    questions: List[str]
