from typing import Any, Dict, List, Optional
from pydantic import Field
from app.core.base_schema import BaseSchema
from app.modules.metadata.dtos.metadata_out import FileMetadataResponse

class FileResponseBase(BaseSchema):
    file_id: str
    original_filename: str
    display_name: str
    file_size: int
    mime_type: str
    storage_path: str
    status: str
    lecturer_only: bool = False
    custom_metadata: Optional[FileMetadataResponse] = Field(default=None)
    file_url: Optional[str] = None
    markdown_file_url: Optional[str] = None
    created_at: str
    updated_at: str
    deleted_at: Optional[str] = None
    deleted_by: Optional[str] = None


class FileListItemResponse(FileResponseBase):
    """Compact file representation used by active and trash list APIs."""


class FileDetailResponse(FileResponseBase):
    table_of_contents: List[str] = Field(default_factory=list)

class BulkDeleteResponse(BaseSchema):
    deleted_count: int
    message: str

class HealthCheckResponse(BaseSchema):
    status: str
    service: str
    version: str
    gemini_api_connected: bool
    mongodb_connected: bool
    redis_connected: bool
    email_consumer_running: Optional[bool] = None

class ErrorResponse(BaseSchema):
    error: str
    message: str
    details: Optional[Dict[str, Any]] = None
