from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, model_validator

YEAR_MIN = 0
YEAR_MAX = 9999

class DocumentType(str, Enum):
    CTDT       = "ctdt"        # Chương trình đào tạo
    CONG_VAN   = "cong_van"    # Công văn
    QUYET_DINH = "quyet_dinh"  # Quyết định

class YearRange(BaseModel):
    """Inclusive integer range [from_year, to_year]."""
    from_year: int = YEAR_MIN
    to_year: int = YEAR_MAX

    @model_validator(mode="after")
    def validate_range(self) -> YearRange:
        if self.from_year > self.to_year:
            raise ValueError(
                f"from_year ({self.from_year}) must be <= to_year ({self.to_year})"
            )
        return self

    def to_flat_dict(self, prefix: str) -> dict:
        return {
            f"{prefix}_from": self.from_year,
            f"{prefix}_to":   self.to_year,
        }

    @classmethod
    def from_null_pair(
        cls,
        from_year: Optional[int],
        to_year: Optional[int],
    ) -> YearRange:
        return cls(
            from_year=from_year if from_year is not None else YEAR_MIN,
            to_year=to_year   if to_year   is not None else YEAR_MAX,
        )

    def contains(self, year: int) -> bool:
        return self.from_year <= year <= self.to_year

class FileMetadata(BaseModel):
    """Fixed metadata attached to every document in the system."""
    enrollment_year: YearRange = Field(default_factory=YearRange)
    academic_year: YearRange = Field(default_factory=YearRange)
    type: DocumentType = DocumentType.CONG_VAN

    def to_qdrant_payload(self) -> dict:
        payload = {}
        payload.update(self.enrollment_year.to_flat_dict("enrollment_year"))
        payload.update(self.academic_year.to_flat_dict("academic_year"))
        payload["type"] = self.type.value
        return payload

class FaqMetadata(BaseModel):
    """Metadata that constrains which users a FAQ applies to."""
    enrollment_year: YearRange = YearRange()
    academic_year: YearRange = YearRange()

    def to_qdrant_payload(self) -> dict:
        payload = {}
        payload.update(self.enrollment_year.to_flat_dict("enrollment_year"))
        payload.update(self.academic_year.to_flat_dict("academic_year"))
        return payload
