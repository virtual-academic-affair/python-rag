from enum import Enum
from typing import Any, Dict, List, Optional, Literal, Union
from pydantic import Field
from app.core.schemas import BaseSchema
from app.modules.rag.retrieval.schemas import SourceCitation

class SystemLabel(str, Enum):
    ClassRegistration = "classRegistration"
    Inquiry = "inquiry"

class RequestData(BaseSchema):
    title: str = Field(..., description="Email title/subject")
    content: str = Field(..., description="Email content/body")
    message_id: Optional[int] = Field(default=None, description="Optional message ID for gRPC tracking")

class LabelClassificationResponse(BaseSchema):
    message_id: Optional[int] = Field(default=None)
    label: SystemLabel

class IngestEmailData(BaseSchema):
    message_id: int = Field(...)
    subject: str = Field(default="")
    sender_email: str = Field(default="")
    sender_name: str = Field(default="")
    content: str = Field(default="")

class IngestMessage(BaseSchema):
    pattern: Optional[str] = None
    data: IngestEmailData

class RegistrationAction(str, Enum):
    Register = "register"
    Cancel = "cancel"
    RequestOpen = "requestOpen"

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

class BaseLabelResponse(BaseSchema):
    message_id: Optional[int] = Field(default=None)
    label: SystemLabel

class ClassRegistrationExtractResponse(BaseLabelResponse):
    label: SystemLabel = Field(default=SystemLabel.ClassRegistration)
    extracted: ClassRegistrationPayload

class InquiryIntent(BaseSchema):
    question: str = Field(description="The main question or intent extracted from the email.")

class InquiryTypesResult(BaseSchema):
    inquiry_types: List[Literal["graduation", "training", "procedure"]] = Field(description="Strict list of one or more inquiry types characterizing this inquiry.")

from app.modules.metadata.schemas import YearRangeSchema

class InquiryFilters(BaseSchema):
    enrollment_year: Optional[YearRangeSchema] = Field(None, description="Enrollment year range derived from email (e.g. K65 -> 2020)")
    academic_year: Optional[YearRangeSchema] = Field(None, description="Academic year range derived from email")
    type: Optional[str] = Field(None, description="Document type")

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

ResponseModel = Union[LabelClassificationResponse, ClassRegistrationExtractResponse, InquiryResponse]

class ProcessResponse(BaseSchema):
    success: bool
    data: Optional[Any] = None
    error: Optional[str] = None
