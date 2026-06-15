from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from app.modules.metadata.models.value_objects import (
    DocumentType,
    FileMetadata,
    FaqMetadata,
    YearRange,
    YEAR_MIN,
    YEAR_MAX,
)
from app.modules.metadata.dtos import (
    FileMetadataSchema,
    FileMetadataUpdateSchema,
    FaqMetadataSchema,
    UnifiedFilterSchema,
)

import logging
from pydantic import ValidationError

logger = logging.getLogger(__name__)

class MetadataValidator:
    """Validates and converts raw dicts from API requests to FileMetadata / FaqMetadata models.
    This class is intentionally stateless — no database dependency.
    """

    def validate_and_parse_file_metadata(
        self, raw: Dict[str, Any]
    ) -> Tuple[bool, List[str], Optional[FileMetadata]]:
        """Validate raw dict (from API JSON) and return a FileMetadata model."""
        errors: List[str] = []

        if not raw:
            return True, [], FileMetadata()

        try:
            schema = FileMetadataSchema.model_validate(raw)
            model = schema.to_model()
            return True, [], model
        except Exception as exc:
            logger.debug(f"FileMetadata validation error: {exc}")
            errors = self._flatten_pydantic_errors(exc)
            return False, errors, None

    def validate_and_parse_file_metadata_update(
        self, raw: Dict[str, Any]
    ) -> Tuple[bool, List[str], Optional[FileMetadataUpdateSchema]]:
        """Validate raw dict (from API JSON) for a file update and return a FileMetadataUpdateSchema model."""
        errors: List[str] = []

        if not raw:
            return True, [], FileMetadataUpdateSchema()

        try:
            schema = FileMetadataUpdateSchema.model_validate(raw)
            return True, [], schema
        except Exception as exc:
            logger.debug(f"FileMetadata update validation error: {exc}")
            errors = self._flatten_pydantic_errors(exc)
            return False, errors, None

    def validate_and_parse_faq_metadata(
        self, raw: Dict[str, Any]
    ) -> Tuple[bool, List[str], Optional[FaqMetadata]]:
        """Validate raw dict and return a FaqMetadata model."""
        errors: List[str] = []

        if not raw:
            return True, [], FaqMetadata()

        try:
            clean_raw = {k: v for k, v in raw.items() if v is not None}
            schema = FaqMetadataSchema.model_validate(clean_raw)
            model = schema.to_model()
            return True, [], model
        except Exception as exc:
            logger.debug(f"FaqMetadata validation error: {exc}")
            errors = self._flatten_pydantic_errors(exc)
            return False, errors, None

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

    @staticmethod
    def _flatten_pydantic_errors(exc: Exception) -> List[str]:
        if isinstance(exc, ValidationError):
            return [f"{'.'.join(str(l) for l in e['loc'])}: {e['msg']}" for e in exc.errors()]
        return [str(exc)]

def _type_display_name(t: DocumentType) -> str:
    return {
        DocumentType.CTDT:       "Chương trình đào tạo",
        DocumentType.CONG_VAN:   "Công văn",
        DocumentType.QUYET_DINH: "Quyết định",
    }.get(t, t.value)

_validator_instance: Optional[MetadataValidator] = None

def get_metadata_service() -> MetadataValidator:
    """Return the singleton MetadataValidator."""
    global _validator_instance
    if _validator_instance is None:
        _validator_instance = MetadataValidator()
    return _validator_instance
