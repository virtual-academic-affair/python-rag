from typing import Any, Dict, List, Optional
from pydantic import Field
from app.core.base_schema import BaseSchema
from app.modules.metadata.dtos.update_metadata import UnifiedFilterSchema

class ChatRetrievePreviewRequest(BaseSchema):
    question: str = Field(..., min_length=1, max_length=2000)
    metadata_filter: Optional[UnifiedFilterSchema] = Field(None, description="Metadata filter using fixed schema")
    top_k: Optional[int] = Field(default=None, ge=1, le=20)
    min_score: Optional[float] = Field(default=None, ge=0)
    include_explain: bool = Field(default=True, description="Whether to include score breakdown details")

class ChatRetrievePreviewItem(BaseSchema):
    rank: int
    file_id: Optional[str] = None
    file_name: Optional[str] = None
    section_path: Optional[str] = None
    score: Optional[float] = None
    explain: Optional[Dict[str, Any]] = None
    text: str

class ChatRetrievePreviewResponse(BaseSchema):
    query: str
    top_k: int
    min_score: float
    count: int
    cache_stats: Optional[Dict[str, Any]] = None
    items: List[ChatRetrievePreviewItem] = Field(default_factory=list)
