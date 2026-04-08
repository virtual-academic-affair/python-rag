"""Pydantic models for request and response schemas."""
from enum import Enum
from typing import Any, Dict, List, Optional, Literal

from pydantic import BaseModel, Field, ConfigDict
from pydantic.alias_generators import to_camel


class BaseSchema(BaseModel):
    """Base schema with camelCase alias generator for all API models."""
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        serialize_by_alias=True,
    )


class SystemLabel(str, Enum):
    """Supported system labels."""

    ClassRegistration = "classRegistration"
    Task = "task"
    Inquiry = "inquiry"
    Other = "other"


class RequestData(BaseSchema):
    """Manual request payload for HTTP endpoint."""

    title: str = Field(..., description="Email title/subject")
    content: str = Field(..., description="Email content/body")


class LabelClassificationResponse(BaseSchema):
    """Classification result for one email."""

    message_id: Optional[int] = Field(default=None)
    label: SystemLabel


class IngestEmailData(BaseSchema):
    """Email data received from RabbitMQ ingest queue."""

    message_id: int = Field(...)
    subject: str = Field(default="")
    sender_email: str = Field(default="")
    sender_name: str = Field(default="")
    content: str = Field(default="")


class IngestMessage(BaseSchema):
    """Wrapper message received from RabbitMQ (pattern optional)."""

    pattern: Optional[str] = None
    data: IngestEmailData



class RegistrationAction(str, Enum):
    """Actions for class registration items."""

    Register = "register"
    Cancel = "cancel"
    RequestOpen = "requestOpen"


class ClassRegistrationItem(BaseSchema):
    """One subject/class registration instruction extracted from email."""

    action: RegistrationAction
    subject_name: str = Field(default="")
    subject_code: str = Field(default="")
    class_name: str = Field(default="")
    slot_info: str = Field(default="")
    is_in_curriculum: bool = Field(default=False)


class ClassRegistrationPayload(BaseSchema):
    """Structured payload for classRegistration emails."""

    message_id: Optional[int] = Field(default=None)
    status: str = Field(default="")
    student_code: str = Field(default="")
    academic_year: Optional[int] = Field(default=None)
    student_name: str = Field(default="")
    note: str = Field(default="")
    items: List[ClassRegistrationItem] = Field(default_factory=list)


class BaseLabelResponse(BaseSchema):
    """Base response for classification endpoints."""

    message_id: Optional[int] = Field(default=None)
    label: SystemLabel


class ClassRegistrationExtractResponse(BaseLabelResponse):
    """Classification + extracted payload for classRegistration."""

    label: SystemLabel = Field(default=SystemLabel.ClassRegistration)
    extracted: ClassRegistrationPayload


class TaskPayload(BaseSchema):
    """Structured payload for task emails."""

    name: str = Field(default="")
    description: str = Field(default="")
    due: Optional[str] = Field(default=None)
    priority: str = Field(default="")
    assigners: List[str] = Field(default_factory=list)
    assignee_ids: List[str] = Field(default_factory=list)
    message_id: Optional[int] = Field(default=None)


class TaskExtractResponse(BaseSchema):
    """Classification + extracted payload for task emails."""

    label: SystemLabel = Field(default=SystemLabel.Task)
    extracted: TaskPayload





class ProcessResponse(BaseSchema):
    """Process response wrapper (kept for compatibility)."""

    success: bool
    data: Optional[Any] = None  # ResponseModel - defined after InquiryExtractResponse
    error: Optional[str] = None


# ====================================
# HEALTH CHECK & ERROR RESPONSES
# ====================================

class HealthCheckResponse(BaseSchema):
    """Health check response."""

    status: str = Field(..., description="Service status: healthy, degraded, unhealthy")
    service: str = Field(..., description="Service name")
    version: str = Field(..., description="Service version")
    gemini_api_connected: bool = Field(default=False, description="Gemini API connectivity")
    mongodb_connected: bool = Field(default=False, description="MongoDB connectivity")


class ErrorResponse(BaseSchema):
    """Standard error response."""

    error: str = Field(..., description="Error code/type")
    message: str = Field(..., description="Human-readable error message")
    details: Optional[Dict[str, Any]] = Field(default=None, description="Additional error context")


# ====================================
# RAG SCHEMAS (for Chat & Email Draft)
# ====================================

class UserContext(BaseSchema):
    """User context information sent from NestJS."""
    user_id: str = Field(..., description="Anonymized user ID")
    name: str = Field(..., description="User name")
    cohort: str = Field(..., description="User cohort/class (e.g., K20)")
    role: str = Field(default="student", description="User role: student, lecture, admin")


class ChatHistoryItem(BaseSchema):
    """Single chat message in history."""
    role: str = Field(..., description="Message sender: user or assistant")
    content: str = Field(..., description="Message content")
    timestamp: Optional[str] = Field(default=None, description="Message timestamp")


class SourceCitation(BaseSchema):
    """Citation information from internal vectorless retrieval sources."""
    citation_id: int = Field(..., description="ID of citation [1], [2], etc.")
    title: Optional[str] = Field(None, description="Document title/name")
    text: Optional[str] = Field(None, description="Relevant text excerpt from document")
    url: Optional[str] = Field(None, description="R2 URL to view the document")
    file_id: Optional[str] = Field(None, description="File ID in database")
    page_index_start: Optional[int] = Field(None, description="Start page index of cited chunk")
    page_index_end: Optional[int] = Field(None, description="End page index of cited chunk")


# ====================================
# INQUIRY WORKFLOW SCHEMAS
# ====================================

class InquiryIntent(BaseSchema):
    """Extracted intent from an inquiry email."""
    question: str = Field(description="The main question or intent extracted from the email.")


class InquiryTypesResult(BaseSchema):
    """Extracted array of inquiry types/categories."""
    inquiry_types: List[Literal["graduation", "training", "procedure"]] = Field(description="Strict list of one or more inquiry types characterizing this inquiry.")


class InquiryFilters(BaseSchema):
    """Extracted filters for metadata-based RAG searching in inquiry flow."""
    academic_year: Optional[str] = Field(None, description="Academic year (e.g. 2024-2025)")
    cohort: Optional[str] = Field(None, description="Cohort (e.g. K65)")


class InquiryPayload(BaseSchema):
    """Structured payload for inquiry emails (email draft response)."""

    answer: str = Field(..., description="Generated reply email body")
    question: Optional[str] = Field(default=None, description="Extracted question/intent from the sender")
    types: List[str] = Field(default_factory=list, description="Categorized inquiry types")
    filters: Optional[InquiryFilters] = Field(default=None, description="Extracted filters used for RAG")
    sources: List[SourceCitation] = Field(default_factory=list, description="RAG source citations")
    message_id: Optional[int] = Field(default=None, description="Original email message ID")


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

class AllowedValueSchema(BaseSchema):
    """Allowed value schema for metadata type API."""
    value: str = Field(..., description="Value stored in DB and used in filter")
    display_name: str = Field(..., description="Display name for UI")
    is_active: bool = Field(True, description="Active status (hidden if False)")
    color: Optional[str] = Field(None, description="Hex color code (e.g., #E74C3C)")
    total_files: int = Field(default=0, description="Count of files using this value")
    visible_roles: List[Literal["lecture", "student"]] = Field(
        default_factory=list,
        description="Roles that can see this value: ['lecture', 'student']. Empty list = Only visible to Admin."
    )


class AllowedValueResponse(AllowedValueSchema):
    pass


class CreateMetadataTypeRequest(BaseSchema):
    """Request body for POST /api/metadata."""
    key: str = Field(..., min_length=1, max_length=50, description="Unique metadata key")
    display_name: str = Field(..., description="Display name for UI")
    description: str = Field("", description="Description (auto-generated if empty)")
    allowed_values: Optional[List[AllowedValueSchema]] = Field(
        None,
        description="Allowed values list (None = free text)"
    )


class UpdateMetadataTypeRequest(BaseSchema):
    """Request body for PATCH /api/metadata/{key}."""
    display_name: Optional[str] = Field(None)
    description: Optional[str] = None
    is_active: Optional[bool] = Field(None)


class AllowedValueCreateRequest(BaseSchema):
    """Request body for POST /api/metadata/{key}/values."""
    value: str = Field(..., description="Value stored in DB and used in filter")
    display_name: str = Field(..., description="Display name for UI")
    is_active: bool = Field(True, description="Active status")
    color: Optional[str] = Field(None, description="Hex color code")
    visible_roles: List[Literal["lecture", "student"]] = Field(
        default_factory=list,
        description="Roles that can see this value"
    )


class AllowedValueUpdateRequest(BaseSchema):
    """Request body for PATCH /api/metadata/{key}/values/{value}."""
    display_name: Optional[str] = Field(None, description="Display name for UI")
    is_active: Optional[bool] = Field(None, description="Active status")
    color: Optional[str] = Field(None, description="Hex color code")
    visible_roles: Optional[List[Literal["lecture", "student"]]] = Field(
        None,
        description="Roles that can see this value"
    )


class MetadataTypeResponse(BaseSchema):
    """Response for metadata type operations."""
    metadata_id: str = Field(..., description="MongoDB ObjectId")
    key: str
    display_name: str
    description: str
    allowed_values: Optional[List[AllowedValueSchema]] = Field(None)
    total_files: int = Field(default=0, description="Count of files using this metadata type")
    is_active: bool
    is_system: bool
    created_at: str
    updated_at: str


class MetadataKeyExistsResponse(BaseSchema):
    """Response for GET /api/metadata/exists."""
    exists: bool = Field(..., description="True if the metadata key exists")


class MetadataTypeListResponse(BaseSchema):
    """Response for GET /api/metadata (Phase 4)."""
    metadata_types: List[MetadataTypeResponse]
    total: int


# ====================================
# CHAT ENDPOINT SCHEMAS
# ====================================

class ChatQueryRequest(BaseSchema):
    """Request body for POST /api/chat/query."""
    question: str = Field(..., min_length=1, max_length=2000, description="User's question")
    chat_history: List[ChatHistoryItem] = Field(default_factory=list, description="Recent chat history (max 10)")
    metadata_filter: Optional[Dict[str, List[str]]] = Field(None, description="Metadata filter as key-value pairs")


class ChatQueryResponse(BaseSchema):
    """Response body for POST /api/chat/query."""
    answer: str = Field(..., description="Generated answer from Gemini")
    sources: Optional[List[SourceCitation]] = Field(default=None, description="Document citations")
    token_usage: Optional[dict] = Field(default=None, description="Token consumption statistics")
    processing_time_ms: int = Field(..., description="Processing time in milliseconds")


class ChatStreamRequest(BaseSchema):
    """Request body for POST /api/chat/stream."""
    question: str = Field(..., min_length=1, max_length=2000)
    chat_history: List[ChatHistoryItem] = Field(default_factory=list)
    metadata_filter: Optional[Dict[str, List[str]]] = Field(None, description="Metadata filter as key-value pairs")



class ChatRetrievePreviewRequest(BaseSchema):
    """Request body for POST /api/chat/retrieve-preview."""
    question: str = Field(..., min_length=1, max_length=2000)
    metadata_filter: Optional[Dict[str, List[str]]] = Field(None, description="Metadata filter as key-value pairs")
    top_k: Optional[int] = Field(default=None, ge=1, le=20)
    min_score: Optional[float] = Field(default=None, ge=0)
    include_explain: bool = Field(default=True, description="Whether to include score breakdown details")


class ChatRetrievePreviewItem(BaseSchema):
    """One retrieved chunk for debugging vectorless relevance."""
    rank: int
    file_id: Optional[str] = None
    file_name: Optional[str] = None
    page_index_start: Optional[int] = None
    page_index_end: Optional[int] = None
    section_path: Optional[str] = None
    score: Optional[float] = None
    explain: Optional[Dict[str, Any]] = None
    text: str


class ChatRetrievePreviewResponse(BaseSchema):
    """Response body for POST /api/chat/retrieve-preview."""
    query: str
    top_k: int
    min_score: float
    count: int
    cache_stats: Optional[Dict[str, Any]] = None
    items: List[ChatRetrievePreviewItem] = Field(default_factory=list)


# ====================================
# FILE MANAGEMENT SCHEMAS
# ====================================

class FileUploadResponse(BaseSchema):
    """Response body for POST /api/files/upload."""
    file_id: str = Field(..., description="MongoDB ObjectId as file ID")
    store_id: str = Field(..., description="Store ID (MongoDB ObjectId)")
    original_filename: str
    display_name: str
    file_size: int = Field(..., description="File size in bytes")
    mime_type: str
    status: str
    gemini_document_name: Optional[str] = None
    custom_metadata: Optional[Dict[str, List[str]]] = Field(default_factory=dict)
    created_at: str = Field(..., description="Creation timestamp (ISO format)")
    file_url: Optional[str] = Field(None, description="Direct download URL from R2")
    markdown_file_url: Optional[str] = Field(None, description="Direct download URL for generated markdown in R2")
    summary: Optional[str] = None
    table_of_contents: List[str] = Field(default_factory=list)
    message: Optional[str] = None



class FileParsePreviewPage(BaseSchema):
    """One parsed markdown page preview."""
    page_index: int = Field(..., description="Page index from parser metadata")
    markdown: str = Field(..., description="Normalized markdown content")


class FileParsePreviewResponse(BaseSchema):
    """Response for PDF parse preview endpoint (Sprint 1)."""
    filename: str
    page_count: int
    pages: List[FileParsePreviewPage] = Field(default_factory=list)



class FileChunkPreviewItem(BaseSchema):
    """One chunk preview item from parsed markdown."""
    chunk_index: int
    page_index_start: int
    page_index_end: int
    section_path: Optional[str] = None
    text: str


class FileChunkPreviewResponse(BaseSchema):
    """Response for PDF chunk preview endpoint (Sprint 2)."""
    filename: str
    page_count: int
    chunk_count: int
    chunk_size_chars: int
    chunk_overlap_chars: int
    chunks: List[FileChunkPreviewItem] = Field(default_factory=list)



class FileIngestChunksResponse(BaseSchema):
    """Response for ingesting PDF chunks into Mongo."""
    file_id: str
    file_name: str
    page_count: int
    chunk_count: int
    inserted_count: int
    deleted_previous_mongo: int


class UpdateFileRequest(BaseSchema):
    """Request body for PATCH /api/files/{file_id}."""
    display_name: str = Field(..., min_length=1, max_length=512, description="New display name for the file")


class FileDetailResponse(BaseSchema):
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
    custom_metadata: Dict[str, List[str]] = Field(default_factory=dict)
    file_url: Optional[str] = None
    markdown_file_url: Optional[str] = None
    summary: Optional[str] = None
    table_of_contents: List[str] = Field(default_factory=list)
    created_at: str
    updated_at: str


class FileListResponse(BaseSchema):
    """Response for GET /api/files."""
    files: List[FileDetailResponse]
    total: int
    page: int
    limit: int


class BatchFileUploadResult(BaseSchema):
    """Result for a single file in batch upload."""
    original_filename: str
    success: bool
    file_id: Optional[str] = None
    store_id: Optional[str] = None
    display_name: Optional[str] = None
    file_url: Optional[str] = None
    error: Optional[str] = None


class BatchFileUploadResponse(BaseSchema):
    """Response for POST /api/files/batch."""
    total: int = Field(..., description="Total files processed")
    successful: int
    failed: int
    results: List[BatchFileUploadResult]


class BulkDeleteResponse(BaseSchema):
    """Response for bulk delete operations."""
    deleted_count: int
    message: str


# ====================================
# SYNC CHECK SCHEMAS
# ====================================

class SyncIssueItem(BaseSchema):
    """Một file bị lệch sync."""
    file_id: Optional[str] = Field(None, description="MongoDB ObjectId (nếu có)")
    original_filename: Optional[str] = None
    storage_path: Optional[str] = None
    gemini_document_name: Optional[str] = None
    issue: str = Field(..., description="Mô tả vấn đề")


class SyncCheckResponse(BaseSchema):
    """Response cho GET /api/files/check-sync."""
    is_synced: bool = Field(..., description="True nếu 3 nơi đồng bộ hoàn toàn")
    total_db: int = Field(..., description="Số file trong MongoDB")
    total_r2: int = Field(..., description="Số file trong R2")
    total_gemini: int = Field(..., description="Số file trong Gemini")
    synced_count: int = Field(..., description="Số file đồng bộ đầy đủ ở cả 3 nơi")
    issues: List[SyncIssueItem] = Field(default_factory=list, description="Danh sách file bị lệch sync")


class SyncActionResult(BaseSchema):
    """Kết quả xử lý một file khi sync."""
    file_id: Optional[str] = None
    original_filename: Optional[str] = None
    storage_path: Optional[str] = None
    gemini_document_name: Optional[str] = None
    action: str = Field(..., description="upload_to_gemini | delete_db | delete_r2 | delete_gemini | delete_all")
    success: bool
    error: Optional[str] = None


class SyncResponse(BaseSchema):
    """Response cho POST /api/files/sync."""
    total_issues: int
    uploaded_to_gemini: int = Field(..., description="Số file được import vào Gemini")
    deleted: int = Field(..., description="Số file/record bị xoá")
    failed: int = Field(..., description="Số lỗi")
    results: List[SyncActionResult]


# ====================================
# STORE MANAGEMENT SCHEMAS
# ====================================

class CreateStoreRequest(BaseSchema):
    """Request body for POST /api/stores."""
    display_name: str = Field(..., min_length=1, max_length=512, description="Display name for the store")
    set_as_default: bool = Field(False, description="Set as default store")


class UpdateStoreRequest(BaseSchema):
    """Request body for PATCH /api/stores/{store_id}."""
    display_name: Optional[str] = Field(None, min_length=1, max_length=512, description="Display name for the store")
    is_default: Optional[bool] = Field(None, description="Set as default store")


class StoreDetailResponse(BaseSchema):
    """Response for GET /api/stores/{store_id}."""
    store_id: str = Field(..., description="MongoDB ObjectId as store ID")
    store_name: str = Field(..., description="Gemini store name (fileSearchStores/xxx)")
    display_name: str
    file_count: int = Field(..., description="Number of active documents")
    total_size: int = Field(..., description="Total size in bytes")
    is_default: bool
    created_at: str
    updated_at: str


class StoreListResponse(BaseSchema):
    """Response for GET /api/stores."""
    stores: List[StoreDetailResponse]
    total: int
    page: int
    limit: int

