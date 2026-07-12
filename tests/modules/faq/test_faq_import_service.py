from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.modules.faq.dtos import FaqImportExcelRequest
from app.modules.faq.services.faq_import_service import FaqImportService


def _request(**overrides):
    data = {
        "question_col": "Question",
        "answer_col": "Answer",
        "metadata_filter_json": "{}",
        "skip_rows": 1,
        "skip_duplicates": True,
        "lecturer_only": False,
    }
    data.update(overrides)
    return FaqImportExcelRequest(**data)


@pytest.mark.asyncio
async def test_faq_import_service_rejects_unknown_metadata_key():
    svc = FaqImportService()

    with pytest.raises(HTTPException) as exc:
        await svc.preview_import(
            filename="faq.csv",
            file_bytes=b"",
            request=_request(metadata_filter_json='{"unknown": "A"}'),
        )

    assert exc.value.status_code == 400
    assert exc.value.detail == "Invalid metadata key: unknown"


@pytest.mark.asyncio
async def test_faq_import_service_preview_uses_csv_parser():
    parsed = {
        "rows": [],
        "total_rows": 0,
        "valid_rows": 0,
        "invalid_rows": 0,
    }
    svc = FaqImportService()

    with patch(
        "app.modules.faq.services.faq_import_service.parse_csv_to_faq_rows",
        return_value=parsed,
    ) as parser:
        response = await svc.preview_import(
            filename="faq.csv",
            file_bytes=b"csv",
            request=_request(metadata_filter_json='{"enrollmentYear": "Year"}'),
        )

    parser.assert_called_once()
    assert response.total_rows == 0


@pytest.mark.asyncio
async def test_faq_import_service_imports_valid_rows_and_appends_parser_errors():
    parsed = {
        "rows": [
            {
                "row_index": 2,
                "question": "Valid question?",
                "answer_rich_text": "<p>Valid answer</p>",
                "answer_markdown": "Valid answer",
                "metadata": {
                    "enrollment_year": {"from_year": 2020, "to_year": 2024},
                    "academic_year": {"from_year": 2024, "to_year": 2025},
                },
                "is_valid": True,
                "error": None,
            },
            {
                "row_index": 3,
                "question": "",
                "answer_rich_text": "",
                "answer_markdown": "",
                "metadata": {
                    "enrollment_year": {"from_year": 2020, "to_year": 2024},
                    "academic_year": {"from_year": 2024, "to_year": 2025},
                },
                "is_valid": False,
                "error": "Question is missing",
            },
        ],
        "total_rows": 2,
        "valid_rows": 1,
        "invalid_rows": 1,
    }
    faq_service = type("FaqServiceStub", (), {})()
    faq_service.bulk_create_faqs = AsyncMock(return_value={
        "total": 1,
        "created": 1,
        "skipped": 0,
        "failed": 0,
        "errors": [],
    })
    svc = FaqImportService(faq_service=faq_service)

    with patch(
        "app.modules.faq.services.faq_import_service.parse_excel_to_faq_rows",
        return_value=parsed,
    ):
        response = await svc.import_faqs(
            filename="faq.xlsx",
            file_bytes=b"xlsx",
            request=_request(lecturer_only=True),
        )

    faq_service.bulk_create_faqs.assert_awaited_once()
    items = faq_service.bulk_create_faqs.await_args.args[0]
    assert len(items) == 1
    assert items[0].lecturer_only is True
    assert response.created == 1
    assert response.failed == 1
    assert response.errors[0].error == "Question is missing"
