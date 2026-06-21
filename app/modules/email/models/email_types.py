"""
Email domain types — enums, value objects, domain entities, payloads.
These are the core business data structures of the email module,
not tied to any HTTP layer or transport format.
"""
from enum import Enum
from typing import List, Optional, Literal
from pydantic import Field
from app.core.base_schema import BaseSchema
from app.modules.metadata.dtos.update_metadata import YearRangeSchema


class SystemLabel(str, Enum):
    ClassRegistration = "classRegistration"
    Inquiry = "inquiry"


class RegistrationAction(str, Enum):
    Register = "register"
    Cancel = "cancel"
    RequestOpen = "requestOpen"


# ---------------------------------------------------------------------------
# Ingest (entry point from RabbitMQ)
# ---------------------------------------------------------------------------

class IngestEmailData(BaseSchema):
    message_id: int = Field(...)
    thread_id: Optional[str] = Field(default=None)
    gmail_message_id: Optional[str] = Field(default=None)
    subject: str = Field(default="")
    sender_email: str = Field(default="")
    sender_name: str = Field(default="")
    content: str = Field(default="")
    student_code: Optional[str] = Field(default=None)
    enrollment_year: Optional[int] = Field(default=None)


class IngestMessage(BaseSchema):
    pattern: Optional[str] = None
    data: IngestEmailData


# ---------------------------------------------------------------------------
# Classification request
# ---------------------------------------------------------------------------

class RequestData(BaseSchema):
    title: str = Field(..., description="Email title/subject")
    content: str = Field(..., description="Email content/body")
    message_id: Optional[int] = Field(default=None, description="Optional message ID for gRPC tracking")


# ---------------------------------------------------------------------------
# Class Registration domain types
# ---------------------------------------------------------------------------

class ClassRegistrationItem(BaseSchema):
    action: RegistrationAction
    subject_name: str = Field(default="")
    subject_code: str = Field(default="")
    class_name: str = Field(default="")
    slot_info: str = Field(default="")
    is_in_curriculum: bool = Field(default=False)


class ClassRegistrationPayload(BaseSchema):
    message_id: Optional[int] = Field(default=None)
    status: str = Field(default="")
    student_code: str = Field(default="")
    academic_year: Optional[int] = Field(default=None)
    student_name: str = Field(default="")
    note: str = Field(default="")
    items: List[ClassRegistrationItem] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Inquiry domain types
# ---------------------------------------------------------------------------

class InquiryIntent(BaseSchema):
    question: str = Field(description="The main question or intent extracted from the email.")


class InquiryTypesResult(BaseSchema):
    inquiry_types: List[Literal["graduation", "training"]] = Field(
        description="Strict list of one or more inquiry types characterizing this inquiry."
    )


class InquiryFilters(BaseSchema):
    enrollment_year: Optional[YearRangeSchema] = Field(
        None, description="Enrollment year range derived from email (e.g. K20 -> 2020)"
    )
    academic_year: Optional[YearRangeSchema] = Field(
        None, description="Academic year range derived from email"
    )
    type: Optional[str] = Field(None, description="Document type")


# ---------------------------------------------------------------------------
# Task domain types
# ---------------------------------------------------------------------------

class TaskPayload(BaseSchema):
    name: str = Field(default="")
    description: str = Field(default="")
    due: Optional[str] = Field(default=None)
    priority: Literal["low", "medium", "high", "urgent"] = Field(default="medium")
    assigners: List[str] = Field(default_factory=list)
    assignee_ids: List[str] = Field(default_factory=list, alias="assigneeIds")
    message_id: Optional[int] = Field(default=None, alias="messageId")
