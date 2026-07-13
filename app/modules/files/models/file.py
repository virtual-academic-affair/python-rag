from enum import Enum
from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field
from beanie import PydanticObjectId
from app.core.base_document import BaseDocument
from app.modules.metadata.models.value_objects import FileMetadata

from pymongo import IndexModel, ASCENDING, DESCENDING

class FileStatus(str, Enum):
    UPLOADING = "uploading"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class FileListProjection(BaseModel):
    """Mongo projection for file list APIs; intentionally excludes TOC and ingestion-only fields."""

    model_config = ConfigDict(populate_by_name=True)

    id: PydanticObjectId = Field(alias="_id")
    original_filename: str
    display_name: str
    file_size: int
    mime_type: str
    storage_path: str
    markdown_storage_path: Optional[str] = None
    status: FileStatus
    lecturer_only: bool = False
    custom_metadata: Optional[FileMetadata] = None
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime] = None
    deleted_by: Optional[str] = None

class FileDocument(BaseDocument):
    display_name: str = Field(..., description="Display name for file")
    display_name_unaccented: Optional[str] = Field(default=None, description="Unaccented display name for search")
    original_filename: str = Field(..., description="Original filename when uploaded")
    original_filename_unaccented: Optional[str] = Field(default=None, description="Unaccented original filename for search")
    
    storage_path: str = Field(..., description="Path in R2 bucket (original file)")
    storage_bucket: str = Field(..., description="R2 bucket name")
    file_size: int = Field(..., description="File size in bytes")
    mime_type: str = Field(..., description="MIME type")
    markdown_storage_path: Optional[str] = Field(None, description="Path of generated markdown file in R2")
    markdown_file_size: Optional[int] = Field(None, description="Generated markdown file size in bytes")

    custom_metadata: Optional[FileMetadata] = Field(
        default=None,
        description="Fixed schema metadata for the file"
    )
    
    table_of_contents: List[str] = Field(default_factory=list, description="Flat list of headings")
    status: FileStatus = Field(default=FileStatus.UPLOADING)
    lecturer_only: bool = Field(default=False, description="Nếu True, chỉ admin/lecture mới xem được")
    deleted_at: Optional[datetime] = Field(default=None, description="Soft-delete timestamp")
    deleted_by: Optional[str] = Field(default=None, description="Admin user ID that soft-deleted the file")
    deleted_corpus_node_keys: List[str] = Field(
        default_factory=list,
        description="Corpus topic assignments retained for restore",
    )

    class Settings:
        name = "files"
        indexes = [
            IndexModel(
                [("display_name_unaccented", ASCENDING)],
                name="idx_files_display_name"
            ),
            "status",
            IndexModel(
                [("deleted_at", ASCENDING), ("status", ASCENDING), ("created_at", DESCENDING)],
                name="idx_files_deleted_status_created",
            ),
        ]
