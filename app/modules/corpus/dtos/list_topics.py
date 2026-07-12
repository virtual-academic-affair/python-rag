from __future__ import annotations

from app.core.base_schema import BaseSchema
from app.modules.corpus.dtos.topic_out import CorpusNodeResponse


class CorpusNodeListResponse(BaseSchema):
    total: int
    items: list[CorpusNodeResponse]
