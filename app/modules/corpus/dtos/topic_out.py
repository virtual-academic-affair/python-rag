from __future__ import annotations

from datetime import datetime

from pydantic import Field

from app.core.base_schema import BaseSchema
from app.modules.metadata.dtos import FaqMetadataResponse, FileMetadataResponse


class CorpusFileRefResponse(BaseSchema):
    id: str
    name: str = ""
    metadata: FileMetadataResponse | None = None
    lecturer_only: bool = False
    updated_at: datetime | None = None


class CorpusFaqRefResponse(BaseSchema):
    id: str
    name: str = ""
    metadata: FaqMetadataResponse | None = None
    lecturer_only: bool = False
    updated_at: datetime | None = None


class CorpusTopicSummaryResponse(BaseSchema):
    node_key: str
    title: str = ""
    summary: str = ""
    parent_key: str | None = None
    file_count: int = 0
    faq_count: int = 0


class CorpusTopicDetailResponse(CorpusTopicSummaryResponse):
    child_keys: list[str] = Field(default_factory=list)
    direct_files: list[CorpusFileRefResponse] = Field(default_factory=list)
    direct_faqs: list[CorpusFaqRefResponse] = Field(default_factory=list)


class CorpusTreeNodeResponse(BaseSchema):
    node_key: str
    title: str = ""
    summary: str = ""
    file_count: int = 0
    faq_count: int = 0
    direct_files: list[CorpusFileRefResponse] = Field(default_factory=list)
    direct_faqs: list[CorpusFaqRefResponse] = Field(default_factory=list)
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
