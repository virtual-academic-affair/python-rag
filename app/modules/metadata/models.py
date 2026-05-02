from typing import Any, Dict, List, Optional
from datetime import datetime, timezone
from pydantic import BaseModel, Field
from dataclasses import dataclass, field
from bson import ObjectId

@dataclass
class AllowedValue:
    value: str                          
    display_name: str                   
    is_active: bool = True              
    color: Optional[str] = None         
    total_files: int = 0                
    def to_dict(self) -> Dict[str, Any]:
        from app.core.text_utils import remove_accents
        return {
            "value": self.value,
            "display_name": self.display_name,
            "display_name_unaccented": remove_accents(self.display_name),
            "is_active": self.is_active,
            "color": self.color,
            "total_files": self.total_files,
        }
    
    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "AllowedValue":
        return AllowedValue(
            value=data["value"],
            display_name=data["display_name"],
            is_active=data.get("is_active", True),
            color=data.get("color"),
            total_files=data.get("total_files", 0),
        )


class MetadataTypeDocument(BaseModel):
    id: Optional[str] = Field(default=None, alias="_id")
    
    key: str = Field(..., description="Unique metadata key (immutable)")
    display_name: str = Field(..., description="Display name for UI")
    display_name_unaccented: Optional[str] = Field(default=None, description="Unaccented display name for search")
    description: str = Field(default="", description="Metadata description")
    
    allowed_values: Optional[List[Dict[str, Any]]] = Field(
        default=None,
        description="List of AllowedValue dicts. None = free text allowed"
    )
    
    is_active: bool = Field(default=True, description="If False, hidden from UI")
    is_system: bool = Field(default=False, description="If True, cannot be deleted")
    
    total_files: int = Field(default=0, description="Total active files having this metadata key")
    
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
        if self.allowed_values is None:
            return None
        return [AllowedValue.from_dict(v) for v in self.allowed_values]
    
    def set_allowed_values(self, values: Optional[List[AllowedValue]]) -> None:
        if values is None:
            self.allowed_values = None
        else:
            self.allowed_values = [v.to_dict() for v in values]
