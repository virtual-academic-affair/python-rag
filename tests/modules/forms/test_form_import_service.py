from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.modules.forms.dtos import FormImportRow
from app.modules.forms.services.form_import_service import FormImportService


@pytest.mark.asyncio
async def test_form_import_service_preview_uses_csv_parser():
    parsed = {
        "rows": [FormImportRow(document_type="Đơn", content_link="https://example.test")],
        "total_previewed": 1,
    }
    svc = FormImportService()

    with patch(
        "app.modules.forms.services.form_import_service.parse_csv_to_form_rows",
        return_value=parsed,
    ) as parser:
        response = await svc.preview_import(
            filename="forms.csv",
            file_bytes=b"csv",
            start_row="2",
            document_type_col="1",
            content_link_col="2",
            notes_col="3",
        )

    parser.assert_called_once()
    assert response.total_previewed == 1
    assert response.rows[0].document_type == "Đơn"


@pytest.mark.asyncio
async def test_form_import_service_raises_parser_error():
    svc = FormImportService()

    with patch(
        "app.modules.forms.services.form_import_service.parse_excel_to_form_rows",
        return_value={"error": "bad sheet"},
    ):
        with pytest.raises(HTTPException) as exc:
            await svc.preview_import(
                filename="forms.xlsx",
                file_bytes=b"xlsx",
                start_row="2",
                document_type_col="1",
                content_link_col="2",
                notes_col="3",
            )

    assert exc.value.status_code == 400
    assert exc.value.detail == "bad sheet"


@pytest.mark.asyncio
async def test_form_import_service_rejects_invalid_start_row():
    svc = FormImportService()

    with pytest.raises(HTTPException) as exc:
        await svc.preview_import(
            filename="forms.xlsx",
            file_bytes=b"xlsx",
            start_row="abc",
            document_type_col="1",
            content_link_col="2",
            notes_col="3",
        )

    assert exc.value.status_code == 400
    assert exc.value.detail == "start_row must be an integer"


@pytest.mark.asyncio
async def test_form_import_service_import_calls_upsert_many():
    rows = [FormImportRow(document_type="Đơn", content_link="https://example.test")]
    form_service = type("FormServiceStub", (), {})()
    form_service.upsert_many = AsyncMock(return_value=1)
    svc = FormImportService(form_service=form_service)

    with patch(
        "app.modules.forms.services.form_import_service.parse_excel_to_form_rows",
        return_value={"rows": rows},
    ):
        response = await svc.import_forms(
            filename="forms.xlsx",
            file_bytes=b"xlsx",
            start_row="2",
            document_type_col="1",
            content_link_col="2",
            notes_col="3",
        )

    form_service.upsert_many.assert_awaited_once_with(rows)
    assert response.count == 1
    assert response.created == 1
