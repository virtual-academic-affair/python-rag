from typing import Optional
from pydantic import Field
from app.core.base_document import BaseDocument
from app.modules.metadata.models.value_objects import FaqMetadata

class FaqDocument(BaseDocument):
    """Represents an approved FAQ in the 'faqs' collection."""
    question: str = Field(..., description="The frequently asked question")
    question_unaccented: str = Field(..., description="Unaccented question for search")
    answer_unaccented: str = Field(..., description="Unaccented answer for search")
    answer_markdown: str = Field(..., description="Answer in Markdown format (internal, for AI)")
    answer_rich_text: Optional[str] = Field(None, description="Answer in HTML Rich Text (for display)")
    metadata_filter: FaqMetadata = Field(default_factory=FaqMetadata, description="Fixed schema metadata filter")
    qdrant_point_id: Optional[str] = Field(None, description="UUID of the point in Qdrant faqs collection")
    is_active: bool = Field(True, description="Whether this FAQ is active and searchable")
    view_count: int = Field(0, description="Number of times this FAQ was matched")
    source: str = Field("manual", description="Source of the FAQ: 'manual' or 'synthesized'")
    candidate_id: Optional[str] = Field(None, description="Reference to FaqCandidate if synthesized")

    class Settings:
        name = "faqs"
