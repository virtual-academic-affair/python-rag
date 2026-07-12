from __future__ import annotations

from app.core.base_schema import BaseSchema


class TopicDeleteResponse(BaseSchema):
    node_key: str
    deleted: bool
