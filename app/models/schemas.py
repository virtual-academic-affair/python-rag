"""Pydantic models for request and response schemas."""
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class SystemLabel(str, Enum):
    """Supported system labels."""

    ClassRegistration = "classRegistration"
    Task = "task"
    Inquiry = "inquiry"
    Other = "other"


class InternalData(BaseModel):
    """Internal data that should be returned exactly as received."""

    mail_id: str = Field(..., description="Mail identifier")
    id_record: str = Field(..., description="Record identifier")


class RequestData(BaseModel):
    """Manual request payload for HTTP endpoint."""

    internal: InternalData
    title: str = Field(..., description="Email title/subject")
    content: str = Field(..., description="Email content/body")


class LabelClassificationResponse(BaseModel):
    """Classification result for one email."""

    internal: InternalData
    label: SystemLabel


class IngestEmailData(BaseModel):
    """Email data received from RabbitMQ ingest queue."""

    email_id: int = Field(..., alias="emailId")
    subject: str = Field(default="")
    sender_email: str = Field(default="", alias="senderEmail")
    sender_name: str = Field(default="", alias="senderName")
    content: str = Field(default="")

    class Config:
        populate_by_name = True


class IngestMessage(BaseModel):
    """Wrapper message received from RabbitMQ (pattern optional)."""

    pattern: Optional[str] = None
    data: IngestEmailData

    class Config:
        populate_by_name = True



class RegistrationAction(str, Enum):
    """Actions for class registration items."""

    Register = "register"
    Cancel = "cancel"
    RequestOpen = "requestOpen"


class ClassRegistrationItem(BaseModel):
    """One subject/class registration instruction extracted from email."""

    action: RegistrationAction
    subject_name: str = Field(default="", alias="subjectName")
    subject_code: str = Field(default="", alias="subjectCode")
    class_name: str = Field(default="", alias="className")
    slot_info: str = Field(default="", alias="slotInfo")
    is_in_curriculum: bool = Field(default=False, alias="isInCurriculum")

    class Config:
        populate_by_name = True


class ClassRegistrationPayload(BaseModel):
    """Structured payload for classRegistration emails."""

    student_code: str = Field(default="", alias="studentCode")
    student_name: str = Field(default="", alias="studentName")
    academic_year: Optional[int] = Field(default=None, alias="academicYear")
    note: str = Field(default="")
    message_id: Optional[int] = Field(default=None, alias="messageId")
    items: List[ClassRegistrationItem] = Field(default_factory=list)

    class Config:
        populate_by_name = True


class ClassRegistrationExtractResponse(BaseModel):
    """Classification + extracted payload for classRegistration."""

    internal: InternalData
    label: SystemLabel = Field(default=SystemLabel.ClassRegistration)
    extracted: ClassRegistrationPayload


ResponseModel = LabelClassificationResponse | ClassRegistrationExtractResponse


class ProcessResponse(BaseModel):
    """Process response wrapper (kept for compatibility)."""

    success: bool
    data: Optional[ResponseModel] = None
    error: Optional[str] = None


class AuthVerifyResponse(BaseModel):
    """Response model for auth verification."""

    success: bool
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
