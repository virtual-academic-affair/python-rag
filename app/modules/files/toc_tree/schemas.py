from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, ConfigDict
from pydantic.alias_generators import to_camel

class BaseSchema(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        serialize_by_alias=True,
    )

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

    model_config = ConfigDict(
        populate_by_name=True,
    )
