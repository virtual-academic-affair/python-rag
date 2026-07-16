from pydantic import Field

from app.core.base_schema import BaseSchema
from app.modules.metadata.dtos import FaqMetadataResponse


class FaqRecommendation(BaseSchema):
    """Draft-ready metadata for creating an FAQ from a chat answer."""

    effective_question: str
    metadata: FaqMetadataResponse
    lecturer_only: bool = Field(
        default=False,
        description="True when at least one source actually used by the answer is lecturer-only",
    )
