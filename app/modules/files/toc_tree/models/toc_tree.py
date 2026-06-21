from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional
from app.core.base_document import BaseDocument

class TocTreeNode(BaseModel):
    title: str
    node_id: str
    line_num: int
    text: Optional[str] = None
    summary: Optional[str] = None
    prefix_summary: Optional[str] = None
    nodes: List["TocTreeNode"] = Field(default_factory=list)

class FileTocTree(BaseDocument):
    file_id: str
    doc_name: str
    doc_description: str
    line_count: int
    structure: List[Dict[str, Any]]  # Raw tree from PageIndex
    markdown_storage_path: Optional[str] = None

    class Settings:
        name = "file_toc_trees"
        indexes = [
            "file_id"
        ]
