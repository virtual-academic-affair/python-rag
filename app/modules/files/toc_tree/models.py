from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone

class TocTreeNode(BaseModel):
    title: str
    node_id: str
    line_num: int
    text: Optional[str] = None
    summary: Optional[str] = None
    prefix_summary: Optional[str] = None
    nodes: List["TocTreeNode"] = Field(default_factory=list)

class FileTocTree(BaseModel):
    id: Optional[str] = Field(default=None, alias="_id")
    file_id: str
    doc_name: str
    doc_description: str
    line_count: int
    structure: List[Dict[str, Any]]  # Raw tree từ PageIndex
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Config:
        populate_by_name = True
