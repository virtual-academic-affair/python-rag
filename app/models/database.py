"""
MongoDB Document Models using Pydantic.
These models represent the structure of documents in MongoDB collections.
"""

from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone
from bson import ObjectId
from dataclasses import dataclass, field

from app.models.enums import FileStatus


# ====================================
# STORE DOCUMENT
# ====================================

class StoreDocument(BaseModel):
    """
    Gemini File Search Store - MongoDB Document.
    
    Mapping với Gemini API:
    - store_name → name (fileSearchStores/xxx)
    - display_name → displayName
    - file_count → activeDocumentsCount (sync từ Gemini)
    - total_size → sizeBytes (sync từ Gemini)
    """
    # MongoDB ID (auto-generated, used as store_id in API)
    id: Optional[str] = Field(default=None, alias="_id")
    
    # Gemini store name (immutable, unique)
    # Format: "fileSearchStores/my-store-123a456b789c"
    store_name: str = Field(..., description="Gemini store name (immutable)")
    
    # Display name (passed to Gemini when creating store)
    display_name: str = Field(..., description="Human-readable display name")
    
    # Statistics (synced from Gemini API)
    file_count: int = Field(default=0, description="activeDocumentsCount from Gemini")
    total_size: int = Field(default=0, description="sizeBytes from Gemini")
    
    # Local settings
    is_default: bool = Field(default=False, description="Default store for uploads")
    
    # Timestamps
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    
    class Config:
        populate_by_name = True
        json_encoders = {ObjectId: str}


# ====================================
# FILE DOCUMENT
# ====================================

class FileDocument(BaseModel):
    """
    File Document - MongoDB Document.
    
    Mapping với Gemini Document:
    - display_name → displayName
    - gemini_document_name → name (fileSearchStores/xxx/documents/yyy)
    - custom_metadata → customMetadata[]
    - status → state (STATE_PENDING/ACTIVE/FAILED)
    """
    # MongoDB ID (auto-generated, used as file_id in API)
    id: Optional[str] = Field(default=None, alias="_id")
    
    # Store reference (MongoDB ObjectId of the store)
    store_id: str = Field(..., description="Reference to store (MongoDB ObjectId)")

    # File identification
    display_name: str = Field(..., description="Display name for file")
    original_filename: str = Field(..., description="Original filename when uploaded")
    
    # R2 storage info
    storage_path: str = Field(..., description="Path in R2 bucket")
    storage_bucket: str = Field(..., description="R2 bucket name")
    file_size: int = Field(..., description="File size in bytes")
    mime_type: str = Field(..., description="MIME type")
    
    # Gemini integration
    gemini_document_name: Optional[str] = Field(
        None, 
        description="Gemini document name: fileSearchStores/xxx/documents/yyy"
    )
    
    # Custom metadata (flexible dict, converted to Gemini CustomMetadata[] on upload)
    custom_metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Custom metadata key-value pairs"
    )
    
    # Status (maps to Gemini Document State)
    status: FileStatus = Field(default=FileStatus.UPLOADING)
    
    # Timestamps
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    
    class Config:
        populate_by_name = True
        json_encoders = {ObjectId: str}


# ====================================
# METADATA TYPE DOCUMENT
# ====================================

@dataclass
class AllowedValue:
    """
    Allowed value for metadata type.
    Used for validation and UI rendering.
    """
    value: str                          # Value stored in DB and used in filter (e.g., 'student')
    display_name: str                   # Display name for UI (e.g., 'Student')
    is_active: bool = True              # False = hidden from UI, but filter still works
    color: Optional[str] = None         # Hex color for this value (e.g., '#E74C3C')
    total_files: int = 0                # Total active files associated with this value
    visible_roles: List[str] = field(default_factory=list)
    # Roles that can see this value: ["lecture", "student"]
    # Empty list = Only visible to Admin (others are hidden)
    # Admin can ALWAYS see all values regardless of this list.
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for MongoDB storage."""
        return {
            "value": self.value,
            "display_name": self.display_name,
            "is_active": self.is_active,
            "color": self.color,
            "total_files": self.total_files,
            "visible_roles": self.visible_roles,
        }
    
    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "AllowedValue":
        """Create from dict loaded from MongoDB."""
        return AllowedValue(
            value=data["value"],
            display_name=data["display_name"],
            is_active=data.get("is_active", True),
            color=data.get("color"),
            total_files=data.get("total_files", 0),
            visible_roles=data.get("visible_roles", []),
        )


class MetadataTypeDocument(BaseModel):
    """
    Metadata Type Definition - MongoDB Document (Phase 4 refactored).
    
    Changes from old version:
    - REMOVED: value_type, validation_rules, support_all_value
    - ADDED: display_name, description, is_active, is_system, color
    - CHANGED: allowed_values is now list[AllowedValue] instead of list[str]
    - has_all_value is derived from allowed_values (True if any entry has value='all')
    """
    # MongoDB ID (auto-generated, used as metadata_id in API)
    id: Optional[str] = Field(default=None, alias="_id")
    
    # Unique key (e.g., 'academic_year', 'cohort', 'access_scope')
    # Cannot be changed after creation
    key: str = Field(..., description="Unique metadata key (immutable)")
    
    # Display name for UI
    display_name: str = Field(..., description="Display name for UI")
    
    # Description (auto-generated by Gemini if empty)
    description: str = Field(default="", description="Metadata description")
    
    # Allowed values (None = free text allowed)
    allowed_values: Optional[List[Dict[str, Any]]] = Field(
        default=None,
        description="List of AllowedValue dicts. None = free text allowed"
    )
    
    # Special flags
    is_active: bool = Field(
        default=True,
        description="If False, hidden from UI (metadata type list)"
    )
    is_system: bool = Field(
        default=False,
        description="If True, cannot be deleted (403 Forbidden)"
    )
    
    # Statistics
    total_files: int = Field(
        default=0, 
        description="Total active files having this metadata key"
    )
    
    # Timestamps
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    
    class Config:
        populate_by_name = True
        json_encoders = {ObjectId: str}
    
    @property
    def has_all_value(self) -> bool:
        """True if allowed_values contains an entry with value='all'."""
        if not self.allowed_values:
            return False
        return any(v.get("value") == "all" for v in self.allowed_values)

    def get_allowed_values(self) -> Optional[List[AllowedValue]]:
        """Get allowed_values as list of AllowedValue objects."""
        if self.allowed_values is None:
            return None
        return [AllowedValue.from_dict(v) for v in self.allowed_values]
    
    def set_allowed_values(self, values: Optional[List[AllowedValue]]) -> None:
        """Set allowed_values from list of AllowedValue objects."""
        if values is None:
            self.allowed_values = None
        else:
            self.allowed_values = [v.to_dict() for v in values]
