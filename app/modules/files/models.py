from enum import Enum
from typing import Dict, List, Optional
from datetime import datetime, timezone
from pydantic import BaseModel, Field
from bson import ObjectId

class FileStatus(str, Enum):
    UPLOADING = "uploading"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"

class FileDocument(BaseModel):
    id: Optional[str] = Field(default=None, alias="_id")
    
    display_name: str = Field(..., description="Display name for file")
    original_filename: str = Field(..., description="Original filename when uploaded")
    
    storage_path: str = Field(..., description="Path in R2 bucket (original file)")
    storage_bucket: str = Field(..., description="R2 bucket name")
    file_size: int = Field(..., description="File size in bytes")
    mime_type: str = Field(..., description="MIME type")
    markdown_storage_path: Optional[str] = Field(None, description="Path of generated markdown file in R2")
    markdown_file_size: Optional[int] = Field(None, description="Generated markdown file size in bytes")

    # Custom metadata properties
    custom_metadata: Dict[str, List[str]] = Field(
        default_factory=dict,
        description="Custom metadata key-value list pairs"
    )
    
    table_of_contents: List[str] = Field(default_factory=list, description="Flat list of headings")
    summary: Optional[str] = Field(None, description="Document summary")
    
    status: FileStatus = Field(default=FileStatus.UPLOADING)


    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    
    class Config:
        populate_by_name = True
        json_encoders = {ObjectId: str}
