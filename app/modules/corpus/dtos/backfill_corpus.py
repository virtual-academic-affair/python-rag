from __future__ import annotations

from app.core.base_schema import BaseSchema


class BackfillStartResponse(BaseSchema):
    status: str
    message: str
