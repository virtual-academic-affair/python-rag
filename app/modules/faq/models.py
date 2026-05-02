"""
MongoDB document models for the FAQ Module.
"""
from typing import List, Optional, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field


class FaqDocument(BaseModel):
    """Represents an approved FAQ in the 'faqs' collection."""
    id: Optional[str] = Field(None, alias="_id")
    question: str = Field(..., description="The frequently asked question")
    question_unaccented: str = Field(..., description="Unaccented question for search")
    answer_unaccented: str = Field(..., description="Unaccented answer for search")
    answer_markdown: str = Field(..., description="Answer in Markdown format (internal, for AI)")
    answer_rich_text: Optional[str] = Field(None, description="Answer in HTML Rich Text (for display)")
    metadata_filter: Dict[str, Any] = Field(default_factory=dict, description="Pre-calculated metadata filter structure")
    qdrant_point_id: Optional[str] = Field(None, description="UUID of the point in Qdrant faqs collection")
    is_active: bool = Field(True, description="Whether this FAQ is active and searchable")
    view_count: int = Field(0, description="Number of times this FAQ was matched")
    source: str = Field("manual", description="Source of the FAQ: 'manual' or 'synthesized'")
    candidate_id: Optional[str] = Field(None, description="Reference to FaqCandidate if synthesized")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")


class FaqCandidateDocument(BaseModel):
    """Represents a suggested FAQ pending admin review in the 'faq_candidates' collection."""
    id: Optional[str] = Field(None, alias="_id")
    question: str = Field(..., description="Suggested question")
    question_unaccented: str = Field(..., description="Unaccented suggested question for search")
    answer_draft_markdown: str = Field(..., description="Draft in Markdown (internal, for AI)")
    answer_draft_unaccented: str = Field(..., description="Unaccented draft answer for search")
    answer_draft_rich_text: Optional[str] = Field(None, description="Draft in HTML Rich Text")
    metadata_filter_suggestion: Dict[str, Any] = Field(default_factory=dict, description="Suggested metadata filters")
    source_type: str = Field(..., description="Source of logs: 'chat', 'inquiry_email', or 'mixed'")
    source_log_ids: List[str] = Field(..., description="List of InteractionLog object IDs in this cluster")
    similar_count: int = Field(..., description="Number of logs in this cluster")
    status: str = Field("pending", description="Review status: 'pending', 'approved', 'rejected'")
    reviewed_by: Optional[str] = Field(None, description="User ID of the admin who reviewed this candidate")
    reviewed_at: Optional[datetime] = Field(None, description="Timestamp of the review")
    review_note: Optional[str] = Field(None, description="Admin notes during review")
    synthesis_batch_id: str = Field(..., description="ID of the synthesis run that generated this candidate")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")


class InteractionLogDocument(BaseModel):
    """
    Represents a logged interaction (Chat or Email Inquiry) in the 'interaction_logs' collection.
    Used for FAQ synthesis. TTL indexed to auto-delete.
    """
    id: Optional[str] = Field(None, alias="_id")
    question: str = Field(..., description="The user's question")
    question_unaccented: str = Field(..., description="Unaccented question, used for exact match deduplication")
    question_vector: Optional[List[float]] = Field(None, description="Vector embedding of the question")
    answer_markdown: str = Field(..., description="The generated answer in Markdown format")
    metadata_filter: Dict[str, Any] = Field(default_factory=dict, description="Filters applied during query")
    source_type: str = Field(..., description="'chat' or 'inquiry_email'")
    email_message_id: Optional[int] = Field(None, description="Email message ID if source_type is inquiry_email")
    processing_time_ms: int = Field(0, description="Processing time in milliseconds")
    expires_at: datetime = Field(..., description="TTL field for auto-deletion by MongoDB")
