from datetime import datetime
from typing import List, Optional
from pydantic import Field
from pymongo import IndexModel, TEXT, ASCENDING, DESCENDING
from app.core.base_document import BaseDocument
from app.modules.metadata.models.value_objects import FaqMetadata

class FaqDocument(BaseDocument):
    """Represents an approved FAQ in the 'faqs' collection."""
    question: str = Field(..., description="The frequently asked question")
    question_unaccented: str = Field(..., description="Unaccented question for search")
    answer_unaccented: str = Field(..., description="Unaccented answer for search")
    answer_markdown: str = Field(..., description="Answer in Markdown format (internal, for AI)")
    answer_rich_text: Optional[str] = Field(None, description="Answer in HTML Rich Text (for display)")
    lecturer_only: bool = Field(default=False, description="Nếu True, chỉ admin/lecture mới xem được")
    metadata_filter: FaqMetadata = Field(default_factory=FaqMetadata, description="Fixed schema metadata filter")
    view_count: int = Field(0, description="Number of times this FAQ was matched")
    source: str = Field(
        "manual",
        description="FAQ provenance: manual, bulk_import, seed, or legacy synthesized",
    )
    deleted_at: Optional[datetime] = Field(default=None, description="Soft-delete timestamp")
    deleted_by: Optional[str] = Field(default=None, description="Admin user ID that soft-deleted the FAQ")
    deleted_corpus_node_keys: List[str] = Field(
        default_factory=list,
        description="Corpus topic assignments retained for restore",
    )

    class Settings:
        name = "faqs"
        indexes = [
            IndexModel(
                [("question_unaccented", TEXT), ("answer_unaccented", TEXT)],
                name="idx_faqs_text"
            ),
            IndexModel(
                [("question_unaccented", ASCENDING)],
                unique=True,
                partialFilterExpression={"deleted_at": None},
                name="idx_faqs_question_unique"
            ),
            IndexModel(
                [("deleted_at", ASCENDING), ("created_at", DESCENDING)],
                name="idx_faqs_deleted_created",
            ),
        ]
