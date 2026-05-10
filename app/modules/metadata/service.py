"""
Metadata Service — Stateless validator for the fixed metadata schema.
Replaces the old database-driven MetadataService entirely.
No MongoDB access — metadata types are hardcoded.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from app.modules.metadata.models import (
    DocumentType,
    FileMetadata,
    FaqMetadata,
    YearRange,
    YEAR_MIN,
    YEAR_MAX,
)
from app.modules.metadata.schemas import FileMetadataSchema, FaqMetadataSchema, UnifiedFilterSchema

import logging

logger = logging.getLogger(__name__)


class MetadataValidator:
    """Validates and converts raw dicts from API requests to FileMetadata / FaqMetadata models.

    This class is intentionally stateless — no database dependency.
    """

    # -----------------------------------------------------------------------
    # File metadata
    # -----------------------------------------------------------------------

    def validate_and_parse_file_metadata(
        self, raw: Dict[str, Any]
    ) -> Tuple[bool, List[str], Optional[FileMetadata]]:
        """Validate raw dict (from API JSON) and return a FileMetadata model.

        Args:
            raw: dict parsed from the `customMetadata` JSON field.

        Returns:
            (is_valid, errors, FileMetadata | None)
        """
        errors: List[str] = []

        if not raw:
            # If metadata is missing or empty, use system defaults
            return True, [], FileMetadata()

        try:
            schema = FileMetadataSchema.model_validate(raw)
            model = schema.to_model()
            return True, [], model
        except Exception as exc:
            logger.debug(f"FileMetadata validation error: {exc}")
            errors = self._flatten_pydantic_errors(exc)
            return False, errors, None

    # -----------------------------------------------------------------------
    # FAQ metadata
    # -----------------------------------------------------------------------

    def validate_and_parse_faq_metadata(
        self, raw: Dict[str, Any]
    ) -> Tuple[bool, List[str], Optional[FaqMetadata]]:
        """Validate raw dict and return a FaqMetadata model."""
        errors: List[str] = []

        if not raw:
            # FAQ metadata is optional — empty dict → unrestricted
            return True, [], FaqMetadata()

        try:
            schema = FaqMetadataSchema.model_validate(raw)
            model = schema.to_model()
            return True, [], model
        except Exception as exc:
            logger.debug(f"FaqMetadata validation error: {exc}")
            errors = self._flatten_pydantic_errors(exc)
            return False, errors, None
    # -----------------------------------------------------------------------
    # Unified Filter (Search/List)
    # -----------------------------------------------------------------------

    def validate_unified_filter(
        self, raw: Dict[str, Any]
    ) -> Tuple[bool, List[str]]:
        """Validate raw dict against UnifiedFilterSchema."""
        errors: List[str] = []

        if not raw:
            return True, []

        try:
            UnifiedFilterSchema.model_validate(raw)
            return True, []
        except Exception as exc:
            logger.debug(f"UnifiedFilter validation error: {exc}")
            errors = self._flatten_pydantic_errors(exc)
            return False, errors

    # -----------------------------------------------------------------------
    # Schema definition (for FE form rendering)
    # -----------------------------------------------------------------------

    def get_schema_definition(self) -> dict:
        """Return a JSON-serializable schema description for the frontend."""
        return {
            "documentTypes": [
                {"value": e.value, "displayName": _type_display_name(e)}
                for e in DocumentType
            ],
            "yearMin": YEAR_MIN,
            "yearMax": YEAR_MAX,
        }

    # -----------------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------------

    @staticmethod
    def _flatten_pydantic_errors(exc: Exception) -> List[str]:
        try:
            from pydantic import ValidationError
            if isinstance(exc, ValidationError):
                return [f"{'.'.join(str(l) for l in e['loc'])}: {e['msg']}" for e in exc.errors()]
        except ImportError:
            pass
        return [str(exc)]


def _type_display_name(t: DocumentType) -> str:
    return {
        DocumentType.CTDT:       "Chương trình đào tạo",
        DocumentType.CONG_VAN:   "Công văn",
        DocumentType.QUYET_DINH: "Quyết định",
    }.get(t, t.value)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------
_validator_instance: Optional[MetadataValidator] = None


def get_metadata_service() -> MetadataValidator:
    """Return the singleton MetadataValidator (kept as `get_metadata_service`
    for backward-compatible call sites)."""
    global _validator_instance
    if _validator_instance is None:
        _validator_instance = MetadataValidator()
    return _validator_instance
