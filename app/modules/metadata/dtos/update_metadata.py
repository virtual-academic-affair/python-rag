from __future__ import annotations

from typing import Optional, List, Any
from pydantic import Field, model_validator, ConfigDict
from app.core.base_schema import BaseSchema
from app.modules.metadata.models.value_objects import (
    DocumentType,
    YearRange,
    FileMetadata,
    FaqMetadata,
    YEAR_MIN,
    YEAR_MAX,
)

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
    def validate_range(self) -> YearRangeSchema:
        f = self.from_year if self.from_year is not None else YEAR_MIN
        t = self.to_year   if self.to_year   is not None else YEAR_MAX
        if f > t:
            raise ValueError(f"fromYear ({f}) must be <= toYear ({t})")
        return self

    def to_model(self) -> YearRange:
        return YearRange.from_null_pair(self.from_year, self.to_year)

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

class FileMetadataUpdateSchema(BaseSchema):
    """Request body for customMetadata when updating a file (all fields optional, no default factories)."""
    enrollment_year: Optional[YearRangeSchema] = Field(
        None,
        description="Enrollment year range the document applies to.",
    )
    academic_year: Optional[YearRangeSchema] = Field(
        None,
        description="Academic year range the document is valid for.",
    )
    type: Optional[DocumentType] = Field(
        None, 
        description="Document type (ctdt | cong_van | quyet_dinh)."
    )

class FaqMetadataSchema(BaseSchema):
    """Request body for FAQ metadata_filter."""
    model_config = ConfigDict(extra="forbid")

    enrollment_year: Optional[YearRangeSchema] = None
    academic_year: Optional[YearRangeSchema] = None

    def to_model(self) -> FaqMetadata:
        return FaqMetadata(
            enrollment_year=self.enrollment_year.to_model() if self.enrollment_year else YearRange(),
            academic_year=self.academic_year.to_model() if self.academic_year else YearRange(),
        )

class FaqMetadataCreateSchema(BaseSchema):
    """Used specifically when creating/updating FAQs to ensure 0-9999 defaults."""
    model_config = ConfigDict(extra="forbid")

    enrollment_year: Optional[YearRangeSchema] = Field(default_factory=YearRangeSchema)
    academic_year: Optional[YearRangeSchema] = Field(default_factory=YearRangeSchema)

    def to_model(self) -> FaqMetadata:
        return FaqMetadata(
            enrollment_year=self.enrollment_year.to_model() if self.enrollment_year else YearRangeSchema().to_model(),
            academic_year=self.academic_year.to_model() if self.academic_year else YearRangeSchema().to_model(),
        )

class UnifiedFilterSchema(BaseSchema):
    """Generic schema for filtering by metadata. All fields are optional."""
    model_config = ConfigDict(extra="forbid")

    enrollment_year: Optional[YearRangeSchema] = None
    academic_year: Optional[YearRangeSchema] = None
    type: Optional[List[DocumentType]] = Field(
        None, 
        description="Filter by document types (array)."
    )

    @model_validator(mode="before")
    @classmethod
    def normalize_type_and_aliases(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "type" in data:
                val = data["type"]
                if isinstance(val, str):
                    if val == "":
                        data["type"] = None
                    else:
                        data["type"] = [val]
                elif isinstance(val, list):
                    if not val:
                        data["type"] = None
                elif val is None:
                    data["type"] = None
        return data

class RelaxedUnifiedFilterSchema(UnifiedFilterSchema):
    """Relaxed version of UnifiedFilterSchema that ignores extra fields (used when skip_validation=True)."""
    model_config = ConfigDict(extra="ignore")
