from typing import Optional
from pydantic import Field, model_validator
from app.core.base_schema import BaseSchema
from app.modules.metadata.dtos.update_metadata import FileMetadataUpdateSchema

class UpdateFileRequest(BaseSchema):
    display_name: Optional[str] = Field(None, min_length=1, max_length=512, description="New display name for the file")
    custom_metadata: Optional[FileMetadataUpdateSchema] = Field(None, description="New custom metadata for the file")
    lecturer_only: Optional[bool] = Field(None, description="Giới hạn chỉ admin/lecture mới xem được")

    @model_validator(mode='after')
    def check_at_least_one_field(self) -> 'UpdateFileRequest':
        if self.display_name is None and self.custom_metadata is None and self.lecturer_only is None:
            raise ValueError("At least one of 'display_name', 'custom_metadata', or 'lecturer_only' must be provided.")
        return self
