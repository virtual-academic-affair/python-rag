from __future__ import annotations

from typing import Optional

from app.core.base_schema import BaseSchema


class TopicCreateRequest(BaseSchema):
    slug: str
    title: str
    summary: str = ""
    parent_key: Optional[str] = None
