from typing import List
from app.core.base_schema import BaseSchema
from app.modules.files.dtos.file_out import FileListItemResponse

class FileListResponse(BaseSchema):
    files: List[FileListItemResponse]
    total: int
    page: int
    limit: int
