"""
Metadata Schemas — API-facing Pydantic schemas for the fixed metadata system.
Uses camelCase aliases (serialize_by_alias=True) to match NestJS frontend convention.
"""
from __future__ import annotations

from typing import Optional, List
from pydantic import Field, model_validator
from app.core.schemas import BaseSchema
from app.modules.metadata.models import (
    DocumentType,
    YearRange,
    FileMetadata,
    FaqMetadata,
    YEAR_MIN,
    YEAR_MAX,
)


# ---------------------------------------------------------------------------
# YearRange — API representation
# ---------------------------------------------------------------------------
class YearRangeSchema(BaseSchema):
    """fromYear / toYear as received from / sent to the frontend.

    Defaults to sentinels (0, 9999) if not provided.
    """
    from_year: int = Field(
        YEAR_MIN,
        description="Lower bound (inclusive). 0 = no lower bound.",
    )
    to_year: int = Field(
        YEAR_MAX,
        description="Upper bound (inclusive). 9999 = no upper bound.",
    )

    @model_validator(mode="after")
    def validate_range(self) -> "YearRangeSchema":
        f = self.from_year if self.from_year is not None else YEAR_MIN
        t = self.to_year   if self.to_year   is not None else YEAR_MAX
        if f > t:
            raise ValueError(f"fromYear ({f}) must be <= toYear ({t})")
        return self

    def to_model(self) -> YearRange:
        return YearRange.from_null_pair(self.from_year, self.to_year)


class YearRangeResponse(BaseSchema):
    """Always returns concrete ints (sentinels kept as-is)."""
    from_year: int
    to_year: int

    @classmethod
    def from_model(cls, r: YearRange) -> "YearRangeResponse":
        return cls(from_year=r.from_year, to_year=r.to_year)


# ---------------------------------------------------------------------------
# FileMetadata — API schemas
# ---------------------------------------------------------------------------
class FileMetadataSchema(BaseSchema):
    """Request body for customMetadata when uploading / updating a file."""
    enrollment_year: Optional[YearRangeSchema] = Field(
        default_factory=YearRangeSchema,
        description="Enrollment year range the document applies to.",
    )
    academic_year: Optional[YearRangeSchema] = Field(
        default_factory=YearRangeSchema,
        description="Academic year range the document is valid for.",
    )
    type: DocumentType = Field(
        DocumentType.CONG_VAN, 
        description="Document type (ctdt | cong_van | quyet_dinh)."
    )

    def to_model(self) -> FileMetadata:
        return FileMetadata(
            enrollment_year=self.enrollment_year.to_model() if self.enrollment_year else YearRangeSchema().to_model(),
            academic_year=self.academic_year.to_model() if self.academic_year else YearRangeSchema().to_model(),
            type=self.type,
        )


class FileMetadataResponse(BaseSchema):
    """Response shape for customMetadata in file list / detail responses."""
    enrollment_year: YearRangeResponse
    academic_year: YearRangeResponse
    type: str

    @classmethod
    def from_model(cls, m: FileMetadata) -> "FileMetadataResponse":
        return cls(
            enrollment_year=YearRangeResponse.from_model(m.enrollment_year),
            academic_year=YearRangeResponse.from_model(m.academic_year),
            type=m.type,
        )


# ---------------------------------------------------------------------------
# FaqMetadata — API schemas
# ---------------------------------------------------------------------------
class FaqMetadataSchema(BaseSchema):
    """Request body for FAQ metadata_filter."""
    enrollment_year: Optional[YearRangeSchema] = None
    academic_year: Optional[YearRangeSchema] = None

    def to_model(self) -> FaqMetadata:
        return FaqMetadata(
            enrollment_year=self.enrollment_year.to_model() if self.enrollment_year else None,
            academic_year=self.academic_year.to_model() if self.academic_year else None,
        )


class FaqMetadataCreateSchema(BaseSchema):
    """Used specifically when creating/updating FAQs to ensure 0-9999 defaults."""
    enrollment_year: Optional[YearRangeSchema] = Field(default_factory=YearRangeSchema)
    academic_year: Optional[YearRangeSchema] = Field(default_factory=YearRangeSchema)

    def to_model(self) -> FaqMetadata:
        # For creation, we always want a concrete model, so we use defaults if None
        return FaqMetadata(
            enrollment_year=self.enrollment_year.to_model() if self.enrollment_year else YearRangeSchema().to_model(),
            academic_year=self.academic_year.to_model() if self.academic_year else YearRangeSchema().to_model(),
        )


class FaqMetadataResponse(BaseSchema):
    enrollment_year: YearRangeResponse
    academic_year: YearRangeResponse

    @classmethod
    def from_model(cls, m: FaqMetadata) -> "FaqMetadataResponse":
        return cls(
            enrollment_year=YearRangeResponse.from_model(m.enrollment_year),
            academic_year=YearRangeResponse.from_model(m.academic_year),
        )


# ---------------------------------------------------------------------------
# Unified Filter Schema — For search / list endpoints
# ---------------------------------------------------------------------------
class UnifiedFilterSchema(BaseSchema):
    """Generic schema for filtering by metadata.
    All fields are optional.
    """
    enrollment_year: Optional[YearRangeSchema] = None
    academic_year: Optional[YearRangeSchema] = None
    type: Optional[List[DocumentType]] = Field(
        None, 
        description="Filter by document types (array)."
    )


# ---------------------------------------------------------------------------
# Schema definition endpoint response
# ---------------------------------------------------------------------------
class MetadataSchemaResponse(BaseSchema):
    """Returned by GET /api/metadata/schema for the frontend to render forms."""
    document_types: List[str] = Field(
        default_factory=lambda: [e.value for e in DocumentType],
        description="Allowed document type values.",
    )
    year_min: int = Field(YEAR_MIN, description="Sentinel for no lower bound.")
    year_max: int = Field(YEAR_MAX, description="Sentinel for no upper bound.")
