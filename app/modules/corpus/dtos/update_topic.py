from __future__ import annotations

from typing import Optional

from app.core.base_schema import BaseSchema


class TopicUpdateRequest(BaseSchema):
    title: Optional[str] = None
    summary: Optional[str] = None
    parent_key: Optional[str] = None
