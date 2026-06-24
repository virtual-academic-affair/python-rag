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

    def merge_file_metadata_update(
        self,
        existing: Optional[FileMetadata | Dict[str, Any]],
        incoming_update: Dict[str, Any],
    ) -> Tuple[bool, List[str], Optional[FileMetadata]]:
        """Merge partial file metadata update into existing metadata and validate it."""
        is_valid, errors, update_schema = self.validate_and_parse_file_metadata_update(incoming_update or {})
        if not is_valid:
            return False, errors, None

        existing_dict = self._metadata_to_dict(existing)
        update_dict = update_schema.model_dump(exclude_unset=True, by_alias=False) if update_schema else {}

        merged = self._merge_year_ranges(existing_dict, update_dict)
        if "type" in existing_dict:
            merged["type"] = existing_dict["type"]
        if "type" in update_dict:
            merged["type"] = update_dict["type"]

        clean_merged = self._clean_metadata_dict(merged)
        return self.validate_and_parse_file_metadata(clean_merged)

    def merge_faq_metadata_update(
        self,
        existing: Optional[FaqMetadata | Dict[str, Any]],
        incoming_update: Dict[str, Any],
    ) -> Tuple[bool, List[str], Optional[FaqMetadata]]:
        """Merge partial FAQ metadata update into existing metadata and validate it."""
        try:
            clean_incoming = {k: v for k, v in (incoming_update or {}).items() if v is not None}
            update_schema = FaqMetadataSchema.model_validate(clean_incoming)
        except Exception as exc:
            return False, self._flatten_pydantic_errors(exc), None

        existing_dict = self._metadata_to_dict(existing)
        update_dict = update_schema.model_dump(exclude_unset=True, by_alias=False) if update_schema else {}
        merged = self._merge_year_ranges(existing_dict, update_dict)
        clean_merged = self._clean_metadata_dict(merged)
        return self.validate_and_parse_faq_metadata(clean_merged)

    def get_schema_definition(self) -> dict:
        """Return a JSON-serializable schema description for the frontend."""
        return {
            "documentTypes": [e.value for e in DocumentType],
            "yearMin": YEAR_MIN,
            "yearMax": YEAR_MAX,
        }

    @staticmethod
    def _metadata_to_dict(metadata: Optional[FileMetadata | FaqMetadata | Dict[str, Any]]) -> Dict[str, Any]:
        if metadata is None:
            return {}
        if isinstance(metadata, dict):
            return metadata
        return metadata.model_dump()

    @staticmethod
    def _merge_year_ranges(existing: Dict[str, Any], incoming: Dict[str, Any]) -> Dict[str, Any]:
        merged: Dict[str, Any] = {}

        for key in ("enrollment_year", "academic_year"):
            if existing.get(key):
                merged[key] = dict(existing[key])

            if key in incoming:
                incoming_range = incoming[key] or {}
                existing_range = merged.get(key) or {}
                merged[key] = {
                    "from_year": (
                        incoming_range.get("from_year")
                        if incoming_range.get("from_year") is not None
                        else existing_range.get("from_year", YEAR_MIN)
                    ),
                    "to_year": (
                        incoming_range.get("to_year")
                        if incoming_range.get("to_year") is not None
                        else existing_range.get("to_year", YEAR_MAX)
                    ),
                }

        return merged

    @staticmethod
    def _clean_metadata_dict(metadata: Dict[str, Any]) -> Dict[str, Any]:
        return {k: v for k, v in metadata.items() if v is not None and v != {}}

    @staticmethod
    def _flatten_pydantic_errors(exc: Exception) -> List[str]:
        if isinstance(exc, ValidationError):
            return [f"{'.'.join(str(l) for l in e['loc'])}: {e['msg']}" for e in exc.errors()]
        return [str(exc)]

_validator_instance: Optional[MetadataValidator] = None

def get_metadata_service() -> MetadataValidator:
    """Return the singleton MetadataValidator."""
    global _validator_instance
    if _validator_instance is None:
        _validator_instance = MetadataValidator()
    return _validator_instance
