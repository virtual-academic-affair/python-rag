from __future__ import annotations

from typing import Any, List
from pydantic import Field
from app.core.base_schema import BaseSchema
from app.modules.metadata.models.value_objects import (
    DocumentType,
    YearRange,
    FileMetadata,
    FaqMetadata,
    YEAR_MIN,
    YEAR_MAX,
)

class YearRangeResponse(BaseSchema):
    """Always returns concrete ints (sentinels kept as-is)."""
    from_year: int
    to_year: int

    @classmethod
    def from_model(cls, r: YearRange) -> YearRangeResponse:
        return cls(from_year=r.from_year, to_year=r.to_year)

class FileMetadataResponse(BaseSchema):
    """Response shape for customMetadata in file list / detail responses."""
    enrollment_year: YearRangeResponse
    academic_year: YearRangeResponse
    type: str

    @classmethod
    def from_model(cls, m: FileMetadata) -> FileMetadataResponse:
        return cls(
            enrollment_year=YearRangeResponse.from_model(m.enrollment_year),
            academic_year=YearRangeResponse.from_model(m.academic_year),
            type=m.type,
        )

class FaqMetadataResponse(BaseSchema):
    enrollment_year: YearRangeResponse
    academic_year: YearRangeResponse

    @classmethod
    def from_model(cls, m: FaqMetadata) -> FaqMetadataResponse:
        return cls(
            enrollment_year=YearRangeResponse.from_model(m.enrollment_year),
            academic_year=YearRangeResponse.from_model(m.academic_year),
        )

class MetadataSchemaResponse(BaseSchema):
    """Returned by GET /api/metadata/schema for the frontend to render forms."""
    document_types: List[str] = Field(
        default_factory=lambda: [e.value for e in DocumentType],
        description="Allowed document type values.",
    )
    year_min: int = Field(YEAR_MIN, description="Sentinel for no lower bound.")
    year_max: int = Field(YEAR_MAX, description="Sentinel for no upper bound.")


class UnifiedFilterResponse(BaseSchema):
    """Typed public representation of a normalized metadata filter."""

    enrollment_year: YearRangeResponse | None = None
    academic_year: YearRangeResponse | None = None
    type: list[str] | None = None

    @classmethod
    def from_mapping(cls, value: dict[str, Any] | None) -> "UnifiedFilterResponse | None":
        if not value:
            return None

        def year_range(item: Any) -> YearRangeResponse | None:
            if not isinstance(item, dict):
                return None
            return YearRangeResponse(
                from_year=int(item.get("from_year", item.get("fromYear", YEAR_MIN))),
                to_year=int(item.get("to_year", item.get("toYear", YEAR_MAX))),
            )

        raw_type = value.get("type")
        return cls(
            enrollment_year=year_range(value.get("enrollment_year") or value.get("enrollmentYear")),
            academic_year=year_range(value.get("academic_year") or value.get("academicYear")),
            type=list(raw_type) if isinstance(raw_type, list) else ([raw_type] if isinstance(raw_type, str) and raw_type else None),
        )
