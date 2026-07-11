from typing import List, Optional
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

class FaqSynthesisRequest(BaseSchema):
    date_from: Optional[str] = Field(None, description="ISO format date. Default is now - LOOKBACK_DAYS")
    date_to: Optional[str] = Field(None, description="ISO format date. Default is now")
    sources: List[str] = Field(default_factory=lambda: ["chat", "inquiry_email"])

class FaqSynthesisResponse(BaseSchema):
    batch_id: str
    candidates_created: int
    total_logs_processed: int
    clusters_found: int
    failed_clusters: int
