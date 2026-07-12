"""FAQ import workflow service."""

from __future__ import annotations

import json
import re
from typing import Any

from fastapi import HTTPException

from app.modules.faq.dtos import (
    FaqBulkCreateItem,
    FaqBulkCreateResponse,
    FaqImportExcelRequest,
    FaqImportPreviewResponse,
)
from app.modules.faq.services.faq_service import FaqService, get_faq_service
from app.modules.faq.utils.excel_parser import parse_csv_to_faq_rows, parse_excel_to_faq_rows
from app.modules.metadata.dtos.update_metadata import FaqMetadataSchema


class FaqImportService:
    def __init__(self, faq_service: FaqService | None = None):
        self._faq_service = faq_service

    async def preview_import(
        self,
        *,
        filename: str | None,
        file_bytes: bytes,
        request: FaqImportExcelRequest,
    ) -> FaqImportPreviewResponse:
        metadata_map = self._parse_metadata_map(request.metadata_filter_json)
        return self._parse_rows(
            filename=filename,
            file_bytes=file_bytes,
            request=request,
            metadata_map=metadata_map,
        )

    async def import_faqs(
        self,
        *,
        filename: str | None,
        file_bytes: bytes,
        request: FaqImportExcelRequest,
    ) -> FaqBulkCreateResponse:
        metadata_map = self._parse_metadata_map(request.metadata_filter_json)
        parsed = self._parse_rows(
            filename=filename,
            file_bytes=file_bytes,
            request=request,
            metadata_map=metadata_map,
        )
        valid_items = [
            FaqBulkCreateItem(
                question=row.question,
                answer_rich_text=row.answer_rich_text,
                metadata_filter=row.metadata.model_dump(by_alias=False),
                lecturer_only=request.lecturer_only,
            )
            for row in parsed.rows
            if row.is_valid
        ]

        faq_service = self._faq_service or await get_faq_service()
        result = await faq_service.bulk_create_faqs(valid_items, skip_duplicates=request.skip_duplicates)
        parser_errors = [
            {"row_index": row.row_index, "question": row.question, "error": row.error}
            for row in parsed.rows
            if not row.is_valid
        ]
        result["errors"].extend(parser_errors)
        result["failed"] += len(parser_errors)
        return FaqBulkCreateResponse.model_validate(result)

    def _parse_rows(
        self,
        *,
        filename: str | None,
        file_bytes: bytes,
        request: FaqImportExcelRequest,
        metadata_map: dict[str, Any],
    ) -> FaqImportPreviewResponse:
        try:
            if filename and filename.lower().endswith(".csv"):
                parsed = parse_csv_to_faq_rows(
                    file_bytes=file_bytes,
                    question_col=request.question_col,
                    answer_col=request.answer_col,
                    metadata_map=metadata_map,
                    skip_rows=request.skip_rows,
                )
            else:
                parsed = parse_excel_to_faq_rows(
                    file_bytes=file_bytes,
                    question_col=request.question_col,
                    answer_col=request.answer_col,
                    metadata_map=metadata_map,
                    sheet_name=request.sheet_name,
                    skip_rows=request.skip_rows,
                )
            return FaqImportPreviewResponse.model_validate(parsed)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    def _parse_metadata_map(self, raw: str | None) -> dict[str, Any]:
        try:
            metadata_map = json.loads(raw) if raw else {}
            if not isinstance(metadata_map, dict):
                raise HTTPException(status_code=400, detail="metadata_filter_json must be a JSON object")
            allowed_keys = self._allowed_metadata_keys()
            for key in metadata_map.keys():
                if key not in allowed_keys:
                    raise HTTPException(status_code=400, detail=f"Invalid metadata key: {key}")
            return metadata_map
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid metadata_filter_json: {exc}") from exc
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Invalid FAQ metadata: {exc}") from exc

    @staticmethod
    def _allowed_metadata_keys() -> set[str]:
        allowed_keys: set[str] = set()
        for name, field in FaqMetadataSchema.model_fields.items():
            allowed_keys.add(name)
            if field.alias:
                allowed_keys.add(field.alias)
            camel = re.sub(r"_([a-z])", lambda match: match.group(1).upper(), name)
            allowed_keys.add(camel)
        return allowed_keys


_faq_import_service_instance: FaqImportService | None = None


def get_faq_import_service() -> FaqImportService:
    global _faq_import_service_instance
    if _faq_import_service_instance is None:
        _faq_import_service_instance = FaqImportService()
    return _faq_import_service_instance
