from enum import Enum
from typing import Any, Dict, List, Optional, Literal, Union
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

class BaseSchema(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        serialize_by_alias=True,
    )

class SystemLabel(str, Enum):
    ClassRegistration = "classRegistration"
    Task = "task"
    Inquiry = "inquiry"
    Other = "other"

class RequestData(BaseSchema):
    title: str = Field(..., description="Email title/subject")
    content: str = Field(..., description="Email content/body")

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

class TaskPayload(BaseSchema):
    name: str = Field(default="")
    description: str = Field(default="")
    due: Optional[str] = Field(default=None)
    priority: str = Field(default="")
    assigners: List[str] = Field(default_factory=list)
    assignee_ids: List[str] = Field(default_factory=list)
    message_id: Optional[int] = Field(default=None)

class TaskExtractResponse(BaseSchema):
    label: SystemLabel = Field(default=SystemLabel.Task)
    extracted: TaskPayload

class SourceCitation(BaseSchema):
    citation_id: int = Field(..., description="ID of citation [1], [2], etc.")
    title: Optional[str] = Field(None, description="Document title/name")
    text: Optional[str] = Field(None, description="Relevant text excerpt from document")
    url: Optional[str] = Field(None, description="R2 URL to view the document")
    file_id: Optional[str] = Field(None, description="File ID in database")
    page_index_start: Optional[int] = Field(None, description="Start page index of cited chunk")
    page_index_end: Optional[int] = Field(None, description="End page index of cited chunk")

class InquiryIntent(BaseSchema):
    question: str = Field(description="The main question or intent extracted from the email.")

class InquiryTypesResult(BaseSchema):
    inquiry_types: List[Literal["graduation", "training", "procedure"]] = Field(description="Strict list of one or more inquiry types characterizing this inquiry.")

class InquiryFilters(BaseSchema):
    academic_year: Optional[str] = Field(None, description="Academic year (e.g. 2024-2025)")
    cohort: Optional[str] = Field(None, description="Cohort (e.g. K65)")

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

ResponseModel = Union[LabelClassificationResponse, ClassRegistrationExtractResponse, InquiryResponse, TaskExtractResponse]

class ProcessResponse(BaseSchema):
    success: bool
    data: Optional[Any] = None
    error: Optional[str] = None
