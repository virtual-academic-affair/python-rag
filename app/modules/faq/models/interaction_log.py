from datetime import datetime
from typing import Optional
from pydantic import Field
from pymongo import IndexModel, ASCENDING
from app.core.base_document import BaseDocument
from app.modules.metadata.models.value_objects import FaqMetadata

class InteractionLogDocument(BaseDocument):
    """
    Represents a logged interaction (Chat or Email Inquiry) in the 'interaction_logs' collection.
    Used for FAQ synthesis. TTL indexed to auto-delete.
    """
    question: str = Field(..., description="The user's question")
    question_unaccented: str = Field(..., description="Unaccented question, used for exact match deduplication")
    answer_markdown: str = Field(..., description="The generated answer in Markdown format")
    metadata_filter: FaqMetadata = Field(default_factory=FaqMetadata, description="Filters applied during query")
    source_type: str = Field(..., description="'chat' or 'inquiry_email'")
    email_message_id: Optional[int] = Field(None, description="Email message ID if source_type is inquiry_email")
    processing_time_ms: int = Field(0, description="Processing time in milliseconds")
    expires_at: datetime = Field(..., description="TTL field for auto-deletion by MongoDB")

    class Settings:
        name = "interaction_logs"
        indexes = [
            IndexModel(
                [("expires_at", ASCENDING)],
                expireAfterSeconds=0,
                name="idx_interaction_logs_ttl"
            )
        ]
