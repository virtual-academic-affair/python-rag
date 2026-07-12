from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import Field

from app.core.base_schema import BaseSchema


class CorpusPayloadRef(BaseSchema):
    id: str
    name: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    lecturer_only: bool = False
    updated_at: datetime | None = None


class CorpusNodeResponse(BaseSchema):
    node_key: str
    title: str = ""
    summary: str = ""
    direct_file_ids: list[str] = Field(default_factory=list)
    direct_faq_ids: list[str] = Field(default_factory=list)
    direct_files: list[CorpusPayloadRef] = Field(default_factory=list)
    direct_faqs: list[CorpusPayloadRef] = Field(default_factory=list)
    subtree_file_ids: list[str] = Field(default_factory=list)
    subtree_faq_ids: list[str] = Field(default_factory=list)
    child_keys: list[str] = Field(default_factory=list)
    parent_key: Optional[str] = None
    file_count: int = 0
    faq_count: int = 0


class CorpusTreeNodeResponse(CorpusNodeResponse):
    has_content: bool = False
    children: list["CorpusTreeNodeResponse"] = Field(default_factory=list)


class CorpusTreeResponse(BaseSchema):
    total_nodes: int
    total_root_nodes: int
    tree: list[CorpusTreeNodeResponse]


class CorpusStatsResponse(BaseSchema):
    total_nodes: int
    total_root_nodes: int
    total_direct_file_links: int
    total_direct_faq_links: int
