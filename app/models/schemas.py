"""Pydantic models for request and response schemas"""
from pydantic import BaseModel, Field
from typing import Optional, Union, Literal, List


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
    day: str = Field(..., description="Day of the week (first 3 letters uppercase, e.g., MON, TUE, WED)")
    time: str = Field(..., description="Class start time in HH:MM:SS format")


class CourseData(BaseModel):
    """Course information"""
    code: str = Field(..., description="Course code")
    name: str = Field(..., description="Course name")


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
    class_data: ClassData = Field(..., alias="class")
    course: CourseData

    class Config:
        populate_by_name = True


class OtherResponse(BaseModel):
    """Response model for other request types"""
    internal: InternalData
    types: List[Literal["administrative_requests", "graduation", "academic_affairs", "other"]] = Field(
        ..., 
        description="Request types"
    )


ResponseModel = Union[ClassRegistrationResponse, OtherResponse]


class ProcessResponse(BaseModel):
    """Process response wrapper"""
    success: bool
    data: Optional[ResponseModel] = None
    error: Optional[str] = None

