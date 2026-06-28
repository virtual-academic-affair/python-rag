from typing import List, Optional
from pydantic import Field
from app.core.base_schema import BaseSchema
from app.modules.metadata.dtos.metadata_out import FileMetadataResponse

class FileUploadRequest(BaseSchema):
    display_name: Optional[str] = None
    custom_metadata: Optional[str] = None
    lecturer_only: bool = False
    client_id: Optional[str] = None

class FileUploadResponse(BaseSchema):
    file_id: str = Field(..., description="MongoDB ObjectId as file ID")
    original_filename: str
    display_name: str
    file_size: int = Field(..., description="File size in bytes")
    mime_type: str
    status: str
    custom_metadata: Optional[FileMetadataResponse] = Field(default=None)
    created_at: str = Field(..., description="Creation timestamp (ISO format)")
    file_url: Optional[str] = Field(None, description="Direct download URL from R2")
    markdown_file_url: Optional[str] = Field(None, description="Direct download URL for generated markdown in R2")
    table_of_contents: List[str] = Field(default_factory=list)
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
