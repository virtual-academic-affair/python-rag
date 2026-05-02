from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

class BaseSchema(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        serialize_by_alias=True,
    )

class AllowedValueSchema(BaseSchema):
    value: str = Field(..., description="Value stored in DB and used in filter")
    display_name: str = Field(..., description="Display name for UI")
    is_active: bool = Field(True, description="Active status (hidden if False)")
    color: Optional[str] = Field(None, description="Hex color code (e.g., #E74C3C)")
    total_files: int = Field(default=0, description="Count of files using this value")

class AllowedValueResponse(AllowedValueSchema):
    pass

class CreateMetadataTypeRequest(BaseSchema):
    key: str = Field(..., min_length=1, max_length=50, description="Unique metadata key")
    display_name: str = Field(..., description="Display name for UI")
    description: str = Field("", description="Description (auto-generated if empty)")
    allowed_values: Optional[List[AllowedValueSchema]] = Field(None, description="Allowed values list (None = free text)")

class UpdateMetadataTypeRequest(BaseSchema):
    display_name: Optional[str] = Field(None)
    description: Optional[str] = None
    is_active: Optional[bool] = Field(None)

class AllowedValueCreateRequest(BaseSchema):
    value: str = Field(..., description="Value stored in DB and used in filter")
    display_name: str = Field(..., description="Display name for UI")
    is_active: bool = Field(True, description="Active status")
    color: Optional[str] = Field(None, description="Hex color code")

class AllowedValueUpdateRequest(BaseSchema):
    display_name: Optional[str] = Field(None, description="Display name for UI")
    is_active: Optional[bool] = Field(None, description="Active status")
    color: Optional[str] = Field(None, description="Hex color code")

class MetadataTypeResponse(BaseSchema):
    metadata_id: str = Field(..., description="MongoDB ObjectId")
    key: str
    display_name: str
    description: str
    allowed_values: Optional[List[AllowedValueSchema]] = Field(None)
    total_files: int = Field(default=0, description="Count of files using this metadata type")
    is_active: bool
    is_system: bool
    created_at: str
    updated_at: str

class MetadataKeyExistsResponse(BaseSchema):
    exists: bool = Field(..., description="True if the metadata key exists")

class MetadataTypeListResponse(BaseSchema):
    metadata_types: List[MetadataTypeResponse]
    total: int
