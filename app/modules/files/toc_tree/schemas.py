from typing import Optional, List, Dict, Any
from pydantic import Field
from app.core.schemas import BaseSchema

class TocTreeNode(BaseSchema):
    node_id: str
    title: str
    line_num: int
    summary: Optional[str] = None
    prefix_summary: Optional[str] = None
    nodes: Optional[List['TocTreeNode']] = None

class TocTreeResponse(BaseSchema):
    doc_name: str
    doc_description: Optional[str] = None
    line_count: int
    structure: List[TocTreeNode]
