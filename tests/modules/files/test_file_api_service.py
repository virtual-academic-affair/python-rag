from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.core.auth import JWTPayload
from app.core.exceptions import NotFoundException
from app.modules.files.models.file import FileStatus
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
    assert kwargs["status"] == FileStatus.READY
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


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["student", "lecture"])
async def test_file_api_service_forces_ready_status_for_non_admin(role):
    file_service = MagicMock()
    file_service.list_files = AsyncMock(return_value=([], 0))
    svc = FileApiService(file_service=file_service)

    await svc.list_files(
        file_status="processing",
        metadata_filter=None,
        keywords=None,
        page=1,
        limit=10,
        user=JWTPayload(sub="u1", role=role),
    )

    assert file_service.list_files.await_args.kwargs["status"] == FileStatus.READY


@pytest.mark.asyncio
async def test_file_api_service_admin_can_list_all_active_statuses():
    file_service = MagicMock()
    file_service.list_files = AsyncMock(return_value=([], 0))
    svc = FileApiService(file_service=file_service)

    await svc.list_files(
        file_status=None,
        metadata_filter=None,
        keywords=None,
        page=1,
        limit=10,
        user=JWTPayload(sub="admin1", role="admin"),
    )

    assert file_service.list_files.await_args.kwargs["status"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize(("role", "requested", "expected"), [
    ("admin", True, True),
    ("lecture", False, False),
    ("student", True, {"$ne": True}),
])
async def test_file_list_lecturer_only_filter_respects_role(role, requested, expected):
    file_service = MagicMock()
    file_service.list_files = AsyncMock(return_value=([], 0))
    svc = FileApiService(file_service=file_service)

    await svc.list_files(
        file_status=None,
        metadata_filter=None,
        keywords=None,
        page=1,
        limit=10,
        user=JWTPayload(sub="u1", role=role),
        lecturer_only=requested,
    )

    assert file_service.list_files.await_args.kwargs["role_filter"]["lecturer_only"] == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["student", "lecture"])
async def test_file_detail_hides_non_ready_file_from_non_admin(role):
    file_service = MagicMock()
    file_service.get_file_by_id = AsyncMock(
        return_value=SimpleNamespace(id="file1", status=FileStatus.PROCESSING, lecturer_only=False)
    )
    svc = FileApiService(file_service=file_service)

    with pytest.raises(NotFoundException):
        await svc.get_file_detail("file1", JWTPayload(sub="u1", role=role))


@pytest.mark.asyncio
async def test_file_download_hides_lecturer_only_file_from_student():
    file_service = MagicMock()
    file_service.get_file_by_id = AsyncMock(
        return_value=SimpleNamespace(id="file1", status=FileStatus.READY, lecturer_only=True)
    )
    file_service.download_file = AsyncMock()
    svc = FileApiService(file_service=file_service)

    with pytest.raises(NotFoundException):
        await svc.download_file("file1", "original", JWTPayload(sub="u1", role="student"))

    file_service.download_file.assert_not_awaited()


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


def test_file_list_item_does_not_expose_table_of_contents():
    file_doc = SimpleNamespace(
        id="file1",
        original_filename="a.pdf",
        display_name="A",
        file_size=10,
        mime_type="application/pdf",
        storage_path="uploads/a.pdf",
        markdown_storage_path=None,
        status=FileStatus.READY,
        lecturer_only=False,
        custom_metadata=None,
        table_of_contents=["Mục không được trả về"],
        created_at=None,
        updated_at=None,
        deleted_at=None,
        deleted_by=None,
    )

    with patch(
        "app.modules.files.services.file_api_service.get_download_url",
        return_value="https://download.test/a.pdf",
    ):
        response = FileApiService.to_file_list_item_response(file_doc)

    assert "tableOfContents" not in response.model_dump(by_alias=True)
