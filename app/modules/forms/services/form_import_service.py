"""Form template import workflow service."""

from __future__ import annotations

from fastapi import HTTPException

from app.modules.forms.dtos import FormBulkCreateResponse, FormImportPreviewResponse
from app.modules.forms.services.form_service import FormService, get_form_service
from app.modules.forms.utils.excel_parser import parse_csv_to_form_rows, parse_excel_to_form_rows


class FormImportService:
    def __init__(self, form_service: FormService | None = None):
        self._form_service = form_service

    async def preview_import(
        self,
        *,
        filename: str | None,
        file_bytes: bytes,
        start_row: str,
        document_type_col: str,
        content_link_col: str,
        notes_col: str | None,
    ) -> FormImportPreviewResponse:
        result = self._parse_rows(
            filename=filename,
            file_bytes=file_bytes,
            start_row=start_row,
            document_type_col=document_type_col,
            content_link_col=content_link_col,
            notes_col=notes_col,
            preview_limit=10,
        )
        if result.get("error"):
            raise HTTPException(status_code=400, detail=result.get("error"))
        return FormImportPreviewResponse(
            rows=[item.model_dump(by_alias=True) for item in result["rows"]],
            total_previewed=result["total_previewed"],
        )

    async def import_forms(
        self,
        *,
        filename: str | None,
        file_bytes: bytes,
        start_row: str,
        document_type_col: str,
        content_link_col: str,
        notes_col: str | None,
    ) -> FormBulkCreateResponse:
        result = self._parse_rows(
            filename=filename,
            file_bytes=file_bytes,
            start_row=start_row,
            document_type_col=document_type_col,
            content_link_col=content_link_col,
            notes_col=notes_col,
        )
        if result.get("error"):
            raise HTTPException(status_code=400, detail=result.get("error"))
        form_service = self._form_service or await get_form_service()
        count = await form_service.upsert_many(result["rows"])
        return FormBulkCreateResponse(
            message=f"Imported/updated {count} form templates successfully.",
            count=count,
            created=count,
        )

    @staticmethod
    def _parse_rows(
        *,
        filename: str | None,
        file_bytes: bytes,
        start_row: str,
        document_type_col: str,
        content_link_col: str,
        notes_col: str | None,
        preview_limit: int | None = None,
    ):
        try:
            start_row_index = int(start_row)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="start_row must be an integer") from exc

        kwargs = {
            "file_bytes": file_bytes,
            "document_type_col": document_type_col,
            "content_link_col": content_link_col,
            "notes_col": notes_col,
            "start_row": start_row_index,
        }
        if preview_limit is not None:
            kwargs["preview_limit"] = preview_limit
        if filename and filename.lower().endswith(".csv"):
            return parse_csv_to_form_rows(**kwargs)
        return parse_excel_to_form_rows(**kwargs)


_form_import_service_instance: FormImportService | None = None


def get_form_import_service() -> FormImportService:
    global _form_import_service_instance
    if _form_import_service_instance is None:
        _form_import_service_instance = FormImportService()
    return _form_import_service_instance
