from typing import Any, Dict, List, Optional
from pydantic import Field
from app.core.base_schema import BaseSchema

class FileDetailResponse(BaseSchema):
    file_id: str
    original_filename: str
    display_name: str
    file_size: int
    mime_type: str
    storage_path: str
    status: str
    custom_metadata: Optional[Any] = Field(default=None)
    file_url: Optional[str] = None
    markdown_file_url: Optional[str] = None
    table_of_contents: List[str] = Field(default_factory=list)
    created_at: str
    updated_at: str

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
    qdrant_connected: bool

class ErrorResponse(BaseSchema):
    error: str
    message: str
    details: Optional[Dict[str, Any]] = None
