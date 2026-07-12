from __future__ import annotations

from typing import Literal

from pydantic import Field

from app.core.base_schema import BaseSchema


class PayloadTopicsUpdateRequest(BaseSchema):
    node_keys: list[str] = Field(default_factory=list)


class CorpusPayloadTopicsResponse(BaseSchema):
    payload_type: Literal["file", "faq"]
    payload_id: str
    name: str
    node_keys: list[str] = Field(default_factory=list)
