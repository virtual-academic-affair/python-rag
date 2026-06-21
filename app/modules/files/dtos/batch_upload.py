from typing import List, Optional
from pydantic import Field
from app.core.base_schema import BaseSchema

class BatchFileUploadRequest(BaseSchema):
    display_names: Optional[str] = None
    metadata_list: Optional[str] = None

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
