from typing import List
from app.core.base_schema import BaseSchema
from app.modules.files.dtos.file_out import FileDetailResponse

class FileListResponse(BaseSchema):
    files: List[FileDetailResponse]
    total: int
    page: int
    limit: int
