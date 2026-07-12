from __future__ import annotations

from app.core.base_schema import BaseSchema


class TopicMergeRequest(BaseSchema):
    target_key: str


class TopicMergeResponse(BaseSchema):
    merged_from: str
    merged_into: str
    files_moved: int
    faqs_moved: int
    children_moved: int
    source_deleted: bool = True
