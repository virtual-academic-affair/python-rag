"""
Email response/output schemas — HTTP API response shapes.
These are the data structures returned by email processing endpoints.
"""
from typing import Any, List, Optional, Union
from pydantic import Field
from app.core.base_schema import BaseSchema
from app.modules.email.models.email_types import SystemLabel, ClassRegistrationPayload, InquiryFilters
from app.modules.rag.query.dtos import SourceCitation


class LabelClassificationResponse(BaseSchema):
    message_id: Optional[int] = Field(default=None)
    label: SystemLabel


class BaseLabelResponse(BaseSchema):
    message_id: Optional[int] = Field(default=None)
    label: SystemLabel


class ClassRegistrationExtractResponse(BaseLabelResponse):
    label: SystemLabel = Field(default=SystemLabel.ClassRegistration)
    extracted: ClassRegistrationPayload


class InquiryPayload(BaseSchema):
    answer: str = Field(..., description="Generated reply email body")
    question: Optional[str] = Field(default=None, description="Extracted question/intent from the sender")
    types: List[str] = Field(default_factory=list, description="Categorized inquiry types")
    filters: Optional[InquiryFilters] = Field(default=None, description="Extracted filters used for RAG")
    sources: List[SourceCitation] = Field(default_factory=list, description="RAG source citations")
    message_id: Optional[int] = Field(default=None, description="Original email message ID")


class InquiryResponse(BaseLabelResponse):
    label: SystemLabel = Field(default=SystemLabel.Inquiry)
    inquiry: InquiryPayload


class MixedIntentResponse(BaseSchema):
    """Returned when an email matches BOTH labels."""
    message_id: Optional[int] = Field(default=None)
    labels: List[SystemLabel] = Field(..., description="All labels detected")
    extracted: ClassRegistrationPayload = Field(..., description="Class registration payload")
    inquiry: InquiryPayload = Field(..., description="Inquiry reply payload")


ResponseModel = Union[
    LabelClassificationResponse,
    ClassRegistrationExtractResponse,
    InquiryResponse,
    MixedIntentResponse,
]


class ProcessResponse(BaseSchema):
    success: bool
    data: Optional[Any] = None
    error: Optional[str] = None
