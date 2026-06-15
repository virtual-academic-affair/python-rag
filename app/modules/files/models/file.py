from enum import Enum
from typing import List, Optional
from pydantic import Field
from app.core.base_document import BaseDocument
from app.modules.metadata.models.value_objects import FileMetadata

from pymongo import IndexModel, ASCENDING

class FileStatus(str, Enum):
    UPLOADING = "uploading"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"

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

    class Settings:
        name = "files"
        indexes = [
            IndexModel(
                [("display_name_unaccented", ASCENDING)],
                name="idx_files_display_name"
            ),
            "status",
        ]
