from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.core.auth import JWTPayload
from app.modules.files.services.file_api_service import FileApiService


@pytest.mark.asyncio
async def test_file_api_service_list_files_builds_student_role_filter():
    file_service = MagicMock()
    file_service.list_files = AsyncMock(return_value=([], 0))
    svc = FileApiService(file_service=file_service)

    response = await svc.list_files(
        file_status=None,
        metadata_filter=None,
        keywords="quy chế",
        page=2,
        limit=10,
        user=JWTPayload(sub="u1", email="student@test.edu", role="student", enrollment_year=2022),
    )

    assert response.total == 0
    file_service.list_files.assert_awaited_once()
    kwargs = file_service.list_files.await_args.kwargs
    assert kwargs["skip"] == 10
    assert kwargs["limit"] == 10
    assert kwargs["keywords"] == "quy chế"
    assert kwargs["role_filter"]["lecturer_only"] == {"$ne": True}
    assert kwargs["role_filter"]["$and"][0]["$or"][1] == {
        "custom_metadata.enrollment_year_from": {"$lte": 2022},
        "custom_metadata.enrollment_year_to": {"$gte": 2022},
    }


@pytest.mark.asyncio
async def test_file_api_service_rejects_invalid_metadata_json():
    svc = FileApiService(file_service=MagicMock())

    with pytest.raises(HTTPException) as exc:
        await svc.list_files(
            file_status=None,
            metadata_filter="{bad",
            keywords=None,
            page=1,
            limit=10,
            user=JWTPayload(sub="u1", email="admin@test.edu", role="admin"),
        )

    assert exc.value.status_code == 400
    assert "Invalid metadataFilter JSON format" in exc.value.detail


def test_file_detail_response_mapping_uses_camel_ready_metadata_shape():
    file_doc = SimpleNamespace(
        id="file1",
        original_filename="a.pdf",
        display_name="A",
        file_size=10,
        mime_type="application/pdf",
        storage_path="uploads/a.pdf",
        markdown_storage_path=None,
        status="ready",
        lecturer_only=False,
        custom_metadata=None,
        table_of_contents=["Mục 1"],
        created_at=None,
        updated_at=None,
    )

    with patch(
        "app.modules.files.services.file_api_service.get_download_url",
        return_value="https://download.test/a.pdf",
    ):
        response = FileApiService.to_file_detail_response(file_doc)

    assert response.file_id == "file1"
    assert response.file_url == "https://download.test/a.pdf"
    assert response.table_of_contents == ["Mục 1"]
