from datetime import datetime
from typing import List, Optional
from pydantic import Field
from app.core.base_document import BaseDocument
from app.modules.metadata.models.value_objects import FaqMetadata

class FaqCandidateDocument(BaseDocument):
    """Represents a suggested FAQ pending admin review in the 'faq_candidates' collection."""
    question: str = Field(..., description="Suggested question")
    question_unaccented: str = Field(..., description="Unaccented suggested question for search")
    answer_draft_markdown: str = Field(..., description="Draft in Markdown (internal, for AI)")
    answer_draft_unaccented: str = Field(..., description="Unaccented draft answer for search")
    answer_draft_rich_text: Optional[str] = Field(None, description="Draft in HTML Rich Text")
    metadata_filter_suggestion: FaqMetadata = Field(default_factory=FaqMetadata, description="Suggested metadata filters")
    source_type: str = Field(..., description="Source of logs: 'chat', 'inquiry_email', or 'mixed'")
    source_log_ids: List[str] = Field(..., description="List of InteractionLog object IDs in this cluster")
    similar_count: int = Field(..., description="Number of logs in this cluster")
    status: str = Field("pending", description="Review status: 'pending', 'approved', 'rejected'")
    reviewed_by: Optional[str] = Field(None, description="User ID of the admin who reviewed this candidate")
    reviewed_at: Optional[datetime] = Field(None, description="Timestamp of the review")
    review_note: Optional[str] = Field(None, description="Admin notes during review")
    synthesis_batch_id: str = Field(..., description="ID of the synthesis run that generated this candidate")

    class Settings:
        name = "faq_candidates"
