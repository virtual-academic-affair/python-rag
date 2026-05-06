"""
Metadata Models — Fixed schema (enrollment_year, academic_year, type).
Replaces the old dynamic MetadataTypeDocument / AllowedValue system.
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, model_validator


# ---------------------------------------------------------------------------
# Sentinel values
# ---------------------------------------------------------------------------
YEAR_MIN = 0       # represents "no lower bound"  (i.e. null from_year)
YEAR_MAX = 9999    # represents "no upper bound"  (i.e. null to_year)


# ---------------------------------------------------------------------------
# Document type enum
# ---------------------------------------------------------------------------
class DocumentType(str, Enum):
    CTDT       = "ctdt"        # Chương trình đào tạo
    CONG_VAN   = "cong_van"    # Công văn
    QUYET_DINH = "quyet_dinh"  # Quyết định


# ---------------------------------------------------------------------------
# Year range
# ---------------------------------------------------------------------------
class YearRange(BaseModel):
    """Inclusive integer range [from_year, to_year].

    Sentinel convention:
      from_year = 0    → no lower bound  (null)
      to_year   = 9999 → no upper bound  (null)
    """
    from_year: int = YEAR_MIN
    to_year: int = YEAR_MAX

    @model_validator(mode="after")
    def validate_range(self) -> "YearRange":
        if self.from_year > self.to_year:
            raise ValueError(
                f"from_year ({self.from_year}) must be <= to_year ({self.to_year})"
            )
        return self

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def to_flat_dict(self, prefix: str) -> dict:
        """Flatten to Qdrant-searchable keys.

        Example: prefix='enrollment_year' →
            {'enrollment_year_from': 2019, 'enrollment_year_to': 9999}
        """
        return {
            f"{prefix}_from": self.from_year,
            f"{prefix}_to":   self.to_year,
        }

    @classmethod
    def from_null_pair(
        cls,
        from_year: Optional[int],
        to_year: Optional[int],
    ) -> "YearRange":
        """Create from nullable ints (None maps to sentinel)."""
        return cls(
            from_year=from_year if from_year is not None else YEAR_MIN,
            to_year=to_year   if to_year   is not None else YEAR_MAX,
        )

    def contains(self, year: int) -> bool:
        """Return True if year falls within [from_year, to_year]."""
        return self.from_year <= year <= self.to_year


# ---------------------------------------------------------------------------
# File metadata (stored in MongoDB + Qdrant payload)
# ---------------------------------------------------------------------------
class FileMetadata(BaseModel):
    """Fixed metadata attached to every document in the system."""

    enrollment_year: YearRange = Field(default_factory=YearRange)
    academic_year: YearRange = Field(default_factory=YearRange)
    type: DocumentType = DocumentType.CONG_VAN

    def to_qdrant_payload(self) -> dict:
        """Flatten to a dict suitable for Qdrant payload 'metadata' field."""
        payload = {}
        payload.update(self.enrollment_year.to_flat_dict("enrollment_year"))
        payload.update(self.academic_year.to_flat_dict("academic_year"))
        payload["type"] = self.type.value
        return payload


# ---------------------------------------------------------------------------
# FAQ metadata (stored inside FAQ documents in MongoDB + Qdrant payload)
# ---------------------------------------------------------------------------
class FaqMetadata(BaseModel):
    """Metadata that constrains which users a FAQ applies to."""

    enrollment_year: YearRange = YearRange()
    academic_year: YearRange = YearRange()
    type: Optional[DocumentType] = None   # None → applies to all types

    def to_qdrant_payload(self) -> dict:
        payload = {}
        payload.update(self.enrollment_year.to_flat_dict("enrollment_year"))
        payload.update(self.academic_year.to_flat_dict("academic_year"))
        payload["type"] = self.type.value if self.type else ""
        return payload

