from typing import Any, Dict, Optional
from pydantic import Field, model_validator
from app.core.base_schema import BaseSchema

class UpdateFileRequest(BaseSchema):
    display_name: Optional[str] = Field(None, min_length=1, max_length=512, description="New display name for the file")
    custom_metadata: Optional[Dict[str, Any]] = Field(None, description="New custom metadata for the file")

    @model_validator(mode='after')
    def check_at_least_one_field(self) -> 'UpdateFileRequest':
        if self.display_name is None and self.custom_metadata is None:
            raise ValueError("At least one of 'display_name' or 'custom_metadata' must be provided.")
        return self
