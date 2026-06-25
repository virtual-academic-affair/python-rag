from __future__ import annotations

from typing import Any, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.core.base_document import BaseDocument


class TocTreeNode(BaseModel):
    model_config = ConfigDict(extra="allow")

    title: str
    node_id: str
    line_num: int
    text: Optional[str] = None
    summary: Optional[str] = None
    prefix_summary: Optional[str] = None
    nodes: List[TocTreeNode] = Field(default_factory=list)


class TocTreeUpsertData(BaseModel):
    model_config = ConfigDict(extra="allow")

    doc_name: str
    doc_description: str = ""
    line_count: int = 0
    structure: List[TocTreeNode] = Field(default_factory=list)
    markdown_storage_path: Optional[str] = None


class FileTocTree(BaseDocument):
    file_id: str
    doc_name: str
    doc_description: str
    line_count: int
    structure: List[TocTreeNode] = Field(default_factory=list)
    markdown_storage_path: Optional[str] = None

    class Settings:
        name = "file_toc_trees"
        indexes = [
            "file_id"
        ]


def serialize_toc_structure(structure: List[TocTreeNode]) -> list[dict[str, Any]]:
    return [node.model_dump(mode="json") for node in structure]
