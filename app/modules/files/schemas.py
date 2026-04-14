from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, ConfigDict
from pydantic.alias_generators import to_camel

class BaseSchema(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        serialize_by_alias=True,
    )

class FileUploadResponse(BaseSchema):
    file_id: str = Field(..., description="MongoDB ObjectId as file ID")
    original_filename: str
    display_name: str
    file_size: int = Field(..., description="File size in bytes")
    mime_type: str
    status: str
    custom_metadata: Optional[Dict[str, List[str]]] = Field(default_factory=dict)
    created_at: str = Field(..., description="Creation timestamp (ISO format)")
    file_url: Optional[str] = Field(None, description="Direct download URL from R2")
    markdown_file_url: Optional[str] = Field(None, description="Direct download URL for generated markdown in R2")
    table_of_contents: List[str] = Field(default_factory=list)
    summary: Optional[str] = None
    message: Optional[str] = None

class FileParsePreviewPage(BaseSchema):
    page_index: int = Field(..., description="Page index from parser metadata")
    markdown: str = Field(..., description="Normalized markdown content")

class FileParsePreviewResponse(BaseSchema):
    filename: str
    page_count: int
    pages: List[FileParsePreviewPage] = Field(default_factory=list)

class FileChunkPreviewItem(BaseSchema):
    chunk_index: int
    page_index_start: int
    page_index_end: int
    section_path: Optional[str] = None
    text: str

class FileChunkPreviewResponse(BaseSchema):
    filename: str
    page_count: int
    chunk_count: int
    chunk_size_chars: int
    chunk_overlap_chars: int
    chunks: List[FileChunkPreviewItem] = Field(default_factory=list)


class UpdateFileRequest(BaseSchema):
    display_name: str = Field(..., min_length=1, max_length=512, description="New display name for the file")

class FileDetailResponse(BaseSchema):
    file_id: str
    original_filename: str
    display_name: str
    file_size: int
    mime_type: str
    storage_path: str
    status: str
    custom_metadata: Dict[str, List[str]] = Field(default_factory=dict)
    file_url: Optional[str] = None
    markdown_file_url: Optional[str] = None
    table_of_contents: List[str] = Field(default_factory=list)
    summary: Optional[str] = None
    created_at: str
    updated_at: str

class FileListResponse(BaseSchema):
    files: List[FileDetailResponse]
    total: int
    page: int
    limit: int

class BatchFileUploadResult(BaseSchema):
    original_filename: str
    success: bool
    file_id: Optional[str] = None
    display_name: Optional[str] = None
    file_url: Optional[str] = None
    error: Optional[str] = None

class BatchFileUploadResponse(BaseSchema):
    total: int = Field(..., description="Total files processed")
    successful: int
    failed: int
    results: List[BatchFileUploadResult]

class BulkDeleteResponse(BaseSchema):
    deleted_count: int
    message: str

class HealthCheckResponse(BaseSchema):
    status: str
    service: str
    version: str
    gemini_api_connected: bool
    mongodb_connected: bool

class ErrorResponse(BaseSchema):
    error: str
    message: str
    details: Optional[Dict[str, Any]] = None
