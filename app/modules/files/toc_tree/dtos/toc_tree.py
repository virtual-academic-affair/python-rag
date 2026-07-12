from typing import Any, Optional, List
from app.core.base_schema import BaseSchema

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

    @classmethod
    def from_model(cls, toc_data: Any) -> "TocTreeResponse":
        return cls(
            doc_name=toc_data.doc_name,
            doc_description=toc_data.doc_description,
            line_count=toc_data.line_count,
            structure=[node.model_dump() for node in toc_data.structure],
        )
