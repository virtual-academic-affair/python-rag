from __future__ import annotations

from app.core.base_schema import BaseSchema
from app.modules.corpus.dtos.topic_out import CorpusTopicSummaryResponse


class CorpusTopicListResponse(BaseSchema):
    total: int
    items: list[CorpusTopicSummaryResponse]
