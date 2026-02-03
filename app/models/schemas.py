"""Pydantic models for request and response schemas"""
from pydantic import BaseModel, Field
from typing import Optional, Union, Literal, List, Dict, Any


class InternalData(BaseModel):
    """Internal data that should be returned exactly as received"""
    mail_id: str = Field(..., description="Mail identifier")
    id_record: str = Field(..., description="Record identifier")


class StudentData(BaseModel):
    """Student information"""
    code: str = Field(..., description="Student code")
    name: str = Field(..., description="Student name")
    class_name: str = Field(..., alias="class", description="Student class")
    year: int = Field(..., description="Enrollment year")

    class Config:
        populate_by_name = True


class ClassData(BaseModel):
    """Class information"""
    code: str = Field(..., description="Class code")
    day: Optional[str] = Field(
        default=None,
        description="Day of the week (first 3 letters uppercase, e.g., MON, TUE, WED)",
    )
    time: Optional[str] = Field(
        default=None, description="Class start time in HH:MM:SS format"
    )
    action: Literal["join", "cancel"] = Field(..., description="Action: join (đăng ký) or cancel (hủy)")


class CourseData(BaseModel):
    """Course information"""
    code: str = Field(..., description="Course code")
    name: str = Field(..., description="Course name")


class CourseClassPair(BaseModel):
    """Course with its associated classes"""
    course: CourseData = Field(..., description="Course information")
    classes: List[ClassData] = Field(..., alias="class", description="List of classes for this course")

    class Config:
        populate_by_name = True


class RequestData(BaseModel):
    """Request data model"""
    internal: InternalData
    title: str = Field(..., description="Email title/subject")
    content: str = Field(..., description="Email content/body")


class ClassRegistrationResponse(BaseModel):
    """Response model for class registration requests"""
    internal: InternalData
    types: List[Literal["class_registration"]] = Field(default=["class_registration"], description="Request types")
    student: StudentData
    courses: List[CourseClassPair] = Field(..., description="List of course-class pairs (each course with its classes)")

class IngestEmailData(BaseModel):
    """Email data received from RabbitMQ ingest queue"""

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


class AdministrativeResponse(BaseModel):
    """Response model for administrative requests"""
    internal: InternalData
    types: List[Literal["administrative"]] = Field(default=["administrative"], description="Request types")


class GraduationResponse(BaseModel):
    """Response model for graduation requests"""
    internal: InternalData
    types: List[Literal["graduation"]] = Field(default=["graduation"], description="Request types")


class AcademicProgrammeResponse(BaseModel):
    """Response model for academic programme requests"""
    internal: InternalData
    types: List[Literal["academic_programme"]] = Field(default=["academic_programme"], description="Request types")


class DepartmentResponse(BaseModel):
    """Response model for department requests"""
    internal: InternalData
    types: List[Literal["department"]] = Field(default=["department"], description="Request types")


class OtherResponse(BaseModel):
    """Response model for other request types"""
    internal: InternalData
    types: List[Literal["other"]] = Field(default=["other"], description="Request types")


ResponseModel = Union[
    ClassRegistrationResponse,
    AdministrativeResponse,
    GraduationResponse,
    AcademicProgrammeResponse,
    DepartmentResponse,
    OtherResponse
]


class ProcessResponse(BaseModel):
    """Process response wrapper"""
    success: bool
    data: Optional[ResponseModel] = None
    error: Optional[str] = None


class AuthVerifyResponse(BaseModel):
    """Response model for auth verification"""
    success: bool
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
