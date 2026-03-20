"""Pydantic models for request and response schemas."""
from enum import Enum
from typing import Any, Dict, List, Optional, Literal

from pydantic import BaseModel, Field


class SystemLabel(str, Enum):
    """Supported system labels."""

    ClassRegistration = "classRegistration"
    Task = "task"
    Inquiry = "inquiry"
    Other = "other"


class RequestData(BaseModel):
    """Manual request payload for HTTP endpoint."""

    title: str = Field(..., description="Email title/subject")
    content: str = Field(..., description="Email content/body")


class LabelClassificationResponse(BaseModel):
    """Classification result for one email."""

    message_id: Optional[int] = Field(default=None, alias="messageId")
    label: SystemLabel

    class Config:
        populate_by_name = True


class IngestEmailData(BaseModel):
    """Email data received from RabbitMQ ingest queue."""

    message_id: int = Field(..., alias="messageId")
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

    message_id: Optional[int] = Field(default=None, alias="messageId")
    status: str = Field(default="")
    student_code: str = Field(default="", alias="studentCode")
    academic_year: Optional[int] = Field(default=None, alias="academicYear")
    student_name: str = Field(default="", alias="studentName")
    note: str = Field(default="")
    items: List[ClassRegistrationItem] = Field(default_factory=list)

    class Config:
        populate_by_name = True


class BaseLabelResponse(BaseModel):
    """Base response for classification endpoints."""

    message_id: Optional[int] = Field(default=None, alias="messageId")
    label: SystemLabel

    class Config:
        populate_by_name = True


class ClassRegistrationExtractResponse(BaseLabelResponse):
    """Classification + extracted payload for classRegistration."""

    label: SystemLabel = Field(default=SystemLabel.ClassRegistration)
    extracted: ClassRegistrationPayload


class TaskPayload(BaseModel):
    """Structured payload for task emails."""

    name: str = Field(default="")
    description: str = Field(default="")
    due: Optional[str] = Field(default=None)
    priority: str = Field(default="")
    assigners: List[str] = Field(default_factory=list)
    assignee_ids: List[str] = Field(default_factory=list, alias="assigneeIds")
    message_id: Optional[int] = Field(default=None, alias="messageId")

    class Config:
        populate_by_name = True


class TaskExtractResponse(BaseModel):
    """Classification + extracted payload for task emails."""

    label: SystemLabel = Field(default=SystemLabel.Task)
    extracted: TaskPayload





class ProcessResponse(BaseModel):
    """Process response wrapper (kept for compatibility)."""

    success: bool
    data: Optional[Any] = None  # ResponseModel - defined after InquiryExtractResponse
    error: Optional[str] = None


# ====================================
# HEALTH CHECK & ERROR RESPONSES
# ====================================

class HealthCheckResponse(BaseModel):
    """Health check response."""

    status: str = Field(..., description="Service status: healthy, degraded, unhealthy")
    service: str = Field(..., description="Service name")
    version: str = Field(..., description="Service version")
    gemini_api_connected: bool = Field(default=False, description="Gemini API connectivity")
    mongodb_connected: bool = Field(default=False, description="MongoDB connectivity")


class ErrorResponse(BaseModel):
    """Standard error response."""

    error: str = Field(..., description="Error code/type")
    message: str = Field(..., description="Human-readable error message")
    details: Optional[Dict[str, Any]] = Field(default=None, description="Additional error context")


# ====================================
# RAG SCHEMAS (for Chat & Email Draft)
# ====================================

class UserContext(BaseModel):
    """User context information sent from NestJS."""
    user_id: str = Field(..., description="Anonymized user ID")
    name: str = Field(..., description="User name")
    cohort: str = Field(..., description="User cohort/class (e.g., K20)")
    role: str = Field(default="student", description="User role: student, staff, admin")


class ChatHistoryItem(BaseModel):
    """Single chat message in history."""
    role: str = Field(..., description="Message sender: user or assistant")
    content: str = Field(..., description="Message content")
    timestamp: Optional[str] = Field(default=None, description="Message timestamp")


class SourceCitation(BaseModel):
    """Citation information from File Search grounding metadata."""
    citation_id: int = Field(..., description="ID of citation [1], [2], etc.")
    title: Optional[str] = Field(None, description="Document title/name")
    text: Optional[str] = Field(None, description="Relevant text excerpt from document")
    url: Optional[str] = Field(None, description="R2 URL to view the document")
    file_id: Optional[str] = Field(None, description="File ID in database")


# ====================================
# INQUIRY WORKFLOW SCHEMAS
# ====================================

class InquiryIntent(BaseModel):
    """Extracted intent from an inquiry email."""
    question: str = Field(description="The main question or intent extracted from the email.")


class InquiryTypesResult(BaseModel):
    """Extracted array of inquiry types/categories."""
    inquiry_types: List[Literal["graduation", "training", "procedure"]] = Field(description="Strict list of one or more inquiry types characterizing this inquiry.", alias="inquiryTypes")


class InquiryPayload(BaseModel):
    """Structured payload for inquiry emails (email draft response)."""
    
    answer: str = Field(..., description="Generated reply email body")
    question: Optional[str] = Field(default=None, description="Extracted question/intent from the sender")
    types: List[str] = Field(default_factory=list, description="Categorized inquiry types")
    sources: List[SourceCitation] = Field(default_factory=list, description="RAG source citations")
    message_id: Optional[int] = Field(default=None, alias="messageId", description="Original email message ID")

    class Config:
        populate_by_name = True


class InquiryResponse(BaseLabelResponse):
    """Classification + email draft payload for inquiry."""

    label: SystemLabel = Field(default=SystemLabel.Inquiry)
    inquiry: InquiryPayload


# ====================================
# UNION RESPONSE MODEL
# ====================================

from typing import Union
from typing_extensions import TypeAlias

ResponseModel: TypeAlias = Union[LabelClassificationResponse, ClassRegistrationExtractResponse, InquiryResponse, TaskExtractResponse]


# ====================================
# METADATA TYPE SCHEMAS (Phase 4)
# ====================================

class AllowedValueSchema(BaseModel):
    """Allowed value schema for metadata type API."""
    value: str = Field(..., description="Value stored in DB and used in filter")
    display_name: str = Field(..., alias="displayName", description="Display name for UI")
    is_active: bool = Field(True, alias="isActive", description="Active status (hidden if False)")
    color: Optional[str] = Field(None, description="Hex color code (e.g., #E74C3C)")
    total_files: int = Field(default=0, alias="totalFiles", description="Count of files using this value")
    
    class Config:
        populate_by_name = True

class AllowedValueResponse(AllowedValueSchema):
    pass


class CreateMetadataTypeRequest(BaseModel):
    """Request body for POST /api/metadata."""
    key: str = Field(..., min_length=1, max_length=50, description="Unique metadata key")
    display_name: str = Field(..., alias="displayName", description="Display name for UI")
    description: str = Field("", description="Description (auto-generated if empty)")
    allowed_values: Optional[List[AllowedValueSchema]] = Field(
        None,
        alias="allowedValues",
        description="Allowed values list (None = free text)"
    )
    
    class Config:
        populate_by_name = True


class UpdateMetadataTypeRequest(BaseModel):
    """Request body for PATCH /api/metadata/{key}."""
    display_name: Optional[str] = Field(None, alias="displayName")
    description: Optional[str] = None
    allowed_values: Optional[List[AllowedValueSchema]] = Field(None, alias="allowedValues")
    is_active: Optional[bool] = Field(None, alias="isActive")
    
    class Config:
        populate_by_name = True


class MetadataTypeResponse(BaseModel):
    """Response for metadata type operations."""
    metadata_id: str = Field(..., alias="metadataId", description="MongoDB ObjectId")
    key: str
    display_name: str = Field(..., alias="displayName")
    description: str
    allowed_values: Optional[List[AllowedValueSchema]] = Field(None, alias="allowedValues")
    total_files: int = Field(default=0, alias="totalFiles", description="Count of files using this metadata type")
    is_active: bool = Field(..., alias="isActive")
    is_system: bool = Field(..., alias="isSystem")
    created_at: str = Field(..., alias="createdAt")
    updated_at: str = Field(..., alias="updatedAt")
    
    class Config:
        populate_by_name = True


class MetadataTypeListResponse(BaseModel):
    """Response for GET /api/metadata (Phase 4)."""
    metadata_types: List[MetadataTypeResponse] = Field(..., alias="metadataTypes")
    total: int
    
    class Config:
        populate_by_name = True


# ====================================
# CHAT ENDPOINT SCHEMAS
# ====================================

class ChatQueryRequest(BaseModel):
    """Request body for POST /api/chat/query."""
    question: str = Field(..., min_length=1, max_length=2000, description="User's question")
    user_context: UserContext = Field(..., description="User information")
    chat_history: List[ChatHistoryItem] = Field(default_factory=list, description="Recent chat history (max 10)")
    store_id: Optional[str] = Field(None, description="Store ID. If not provided, uses default store.")
    metadata_filter: Optional[Dict[str, Any]] = Field(None, description="Metadata filter as key-value pairs")


class ChatQueryResponse(BaseModel):
    """Response body for POST /api/chat/query."""
    answer: str = Field(..., description="Generated answer from Gemini")
    sources: Optional[List[SourceCitation]] = Field(default=None, description="Document citations")
    token_usage: Optional[dict] = Field(default=None, description="Token consumption statistics")
    processing_time_ms: int = Field(..., description="Processing time in milliseconds")


class ChatStreamRequest(BaseModel):
    """Request body for POST /api/chat/stream."""
    question: str = Field(..., min_length=1, max_length=2000)
    user_context: UserContext
    chat_history: List[ChatHistoryItem] = Field(default_factory=list)
    store_id: Optional[str] = Field(None, description="Store ID. If not provided, uses default store.")
    metadata_filter: Optional[Dict[str, Any]] = Field(None, description="Metadata filter as key-value pairs")


# ====================================
# FILE MANAGEMENT SCHEMAS
# ====================================

class FileUploadResponse(BaseModel):
    """Response body for POST /api/files/upload."""
    file_id: str = Field(..., description="MongoDB ObjectId as file ID")
    store_id: str = Field(..., description="Store ID (MongoDB ObjectId)")
    original_filename: str
    display_name: str
    file_size: int = Field(..., description="File size in bytes")
    mime_type: str
    status: str
    gemini_document_name: Optional[str] = None
    custom_metadata: Optional[Dict[str, Any]] = Field(default_factory=dict)
    created_at: str = Field(..., description="Creation timestamp (ISO format)")
    message: Optional[str] = None


class FileDetailResponse(BaseModel):
    """Response for GET /api/files/{file_id}."""
    file_id: str
    store_id: str
    original_filename: str
    display_name: str
    file_size: int
    mime_type: str
    storage_path: str
    status: str
    gemini_document_name: Optional[str] = None
    custom_metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: str
    updated_at: str


class FileListResponse(BaseModel):
    """Response for GET /api/files."""
    files: List[FileDetailResponse]
    total: int
    page: int
    limit: int


class BatchFileUploadResult(BaseModel):
    """Result for a single file in batch upload."""
    original_filename: str
    success: bool
    file_id: Optional[str] = None
    store_id: Optional[str] = None
    display_name: Optional[str] = None
    error: Optional[str] = None


class BatchFileUploadResponse(BaseModel):
    """Response for POST /api/files/batch."""
    total: int = Field(..., description="Total files processed")
    successful: int
    failed: int
    results: List[BatchFileUploadResult]


class BulkDeleteResponse(BaseModel):
    """Response for bulk delete operations."""
    deleted_count: int
    message: str


# ====================================
# SYNC CHECK SCHEMAS
# ====================================

class SyncIssueItem(BaseModel):
    """Một file bị lệch sync."""
    file_id: Optional[str] = Field(None, description="MongoDB ObjectId (nếu có)")
    original_filename: Optional[str] = None
    storage_path: Optional[str] = None
    gemini_document_name: Optional[str] = None
    issue: str = Field(..., description="Mô tả vấn đề")


class SyncCheckResponse(BaseModel):
    """Response cho GET /api/files/check-sync."""
    is_synced: bool = Field(..., description="True nếu 3 nơi đồng bộ hoàn toàn")
    total_db: int = Field(..., description="Số file trong MongoDB")
    total_r2: int = Field(..., description="Số file trong R2")
    total_gemini: int = Field(..., description="Số file trong Gemini")
    synced_count: int = Field(..., description="Số file đồng bộ đầy đủ ở cả 3 nơi")
    issues: List[SyncIssueItem] = Field(default_factory=list, description="Danh sách file bị lệch sync")


class SyncActionResult(BaseModel):
    """Kết quả xử lý một file khi sync."""
    file_id: Optional[str] = None
    original_filename: Optional[str] = None
    storage_path: Optional[str] = None
    gemini_document_name: Optional[str] = None
    action: str = Field(..., description="upload_to_gemini | delete_db | delete_r2 | delete_gemini | delete_all")
    success: bool
    error: Optional[str] = None


class SyncResponse(BaseModel):
    """Response cho POST /api/files/sync."""
    total_issues: int
    uploaded_to_gemini: int = Field(..., description="Số file được import vào Gemini")
    deleted: int = Field(..., description="Số file/record bị xoá")
    failed: int = Field(..., description="Số lỗi")
    results: List[SyncActionResult]


# ====================================
# STORE MANAGEMENT SCHEMAS
# ====================================

class CreateStoreRequest(BaseModel):
    """Request body for POST /api/stores."""
    display_name: str = Field(..., min_length=1, max_length=512, description="Display name for the store")
    set_as_default: bool = Field(False, description="Set as default store")


class UpdateStoreRequest(BaseModel):
    """Request body for PATCH /api/stores/{store_id}."""
    display_name: Optional[str] = Field(None, min_length=1, max_length=512, description="Display name for the store")
    is_default: Optional[bool] = Field(None, description="Set as default store")


class StoreDetailResponse(BaseModel):
    """Response for GET /api/stores/{store_id}."""
    store_id: str = Field(..., description="MongoDB ObjectId as store ID")
    store_name: str = Field(..., description="Gemini store name (fileSearchStores/xxx)")
    display_name: str
    file_count: int = Field(..., description="Number of active documents")
    total_size: int = Field(..., description="Total size in bytes")
    is_default: bool
    created_at: str
    updated_at: str


class StoreListResponse(BaseModel):
    """Response for GET /api/stores."""
    stores: List[StoreDetailResponse]
    total: int
    page: int
    limit: int

