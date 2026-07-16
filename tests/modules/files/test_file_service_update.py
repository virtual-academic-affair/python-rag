from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.files.models.file import FileDocument, FileStatus
from app.modules.files.services.file_service import FileService
from app.modules.rag.ingestion import FileIngestionResult


def _make_file(**kwargs):
    defaults = {
        "display_name": "Tên cũ",
        "display_name_unaccented": "ten cu",
        "original_filename": "file.pdf",
        "original_filename_unaccented": "file.pdf",
        "storage_path": "uploads/file.pdf",
        "storage_bucket": "bucket",
        "file_size": 100,
        "mime_type": "application/pdf",
        "custom_metadata": None,
        "lecturer_only": False,
    }
    defaults.update(kwargs)
    return FileDocument.model_construct(**defaults)


@pytest.mark.asyncio
@patch("app.modules.rag.ingestion.corpus_linker.get_corpus_linker")
async def test_update_file_display_name_does_not_reindex_corpus(mock_get_linker):
    svc = FileService.__new__(FileService)
    doc = _make_file()
    repo = MagicMock()
    repo.find_by_id = AsyncMock(return_value=doc)
    repo.save = AsyncMock(side_effect=lambda d: d)
    svc._file_repo = repo
    svc._metadata_svc = None

    saved = await svc.update_file("file1", display_name="Tên mới")

    assert saved.display_name == "Tên mới"
    repo.save.assert_awaited_once()
    mock_get_linker.assert_not_called()


@pytest.mark.asyncio
async def test_find_file_ids_for_corpus_builds_filter_in_file_domain():
    svc = FileService.__new__(FileService)
    repo = MagicMock()
    repo.find_ids_by_query = AsyncMock(return_value={"file1"})
    svc._file_repo = repo
    svc._metadata_svc = None

    result = await svc.find_ids_for_corpus(
        {"enrollment_year": {"from_year": 2022, "to_year": 2022}},
        "student",
    )

    assert result == {"file1"}
    query = repo.find_ids_by_query.await_args.args[0]
    assert query["status"] == FileStatus.READY.value
    assert query["deleted_at"] is None
    assert query["lecturer_only"] == {"$ne": True}
    assert query["custom_metadata.enrollment_year.from_year"] == {"$lte": 2022}


@pytest.mark.parametrize("role", ["lecture", "admin"])
@pytest.mark.asyncio
async def test_find_file_ids_for_corpus_privileged_roles_include_both_visibility_values(role):
    svc = FileService.__new__(FileService)
    repo = MagicMock()
    repo.find_ids_by_query = AsyncMock(return_value={"public", "restricted"})
    svc._file_repo = repo
    svc._metadata_svc = None

    result = await svc.find_ids_for_corpus({}, role)

    assert result == {"public", "restricted"}
    query = repo.find_ids_by_query.await_args.args[0]
    assert query["status"] == FileStatus.READY.value
    assert query["deleted_at"] is None
    assert "lecturer_only" not in query


@pytest.mark.asyncio
async def test_process_file_background_uses_ingestion_service_and_marks_ready():
    svc = FileService.__new__(FileService)
    doc = _make_file(storage_path="uploads/file.pdf")
    repo = MagicMock()
    repo.find_by_id = AsyncMock(return_value=doc)
    repo.mark_processing = AsyncMock()
    repo.mark_ready = AsyncMock(return_value=doc)
    repo.mark_failed = AsyncMock()
    repo.find_by_id_including_deleted = AsyncMock(return_value=doc)
    svc._file_repo = repo

    ingestion = MagicMock()
    ingestion.ingest_file = AsyncMock(return_value=FileIngestionResult(
        markdown_storage_path="uploads/file.md",
        markdown_file_size=42,
        table_of_contents=["Mục 1"],
        summary="Mô tả",
        line_count=12,
        node_keys=["topic-1"],
    ))
    ingestion.cleanup_file_artifacts = AsyncMock()

    with patch(
        "app.modules.files.services.file_upload_service.get_ingestion_service",
        return_value=ingestion,
    ), patch("app.modules.files.services.file_upload_service.cleanup_temp_file") as cleanup_temp:
        await svc.process_file_background(
            file_id="file1",
            file_path="/tmp/file.pdf",
            display_name="Tài liệu",
            custom_metadata={"ignored": True},
        )

    ingestion.ingest_file.assert_awaited_once_with(
        file_id="file1",
        display_name="Tài liệu",
        file_path="/tmp/file.pdf",
        original_storage_path="uploads/file.pdf",
    )
    repo.mark_ready.assert_awaited_once_with(
        file_id="file1",
        markdown_storage_path="uploads/file.md",
        markdown_file_size=42,
        table_of_contents=["Mục 1"],
    )
    ingestion.cleanup_file_artifacts.assert_not_awaited()
    repo.mark_failed.assert_not_awaited()
    cleanup_temp.assert_called_once_with("/tmp/file.pdf")


@pytest.mark.asyncio
async def test_process_file_background_cleans_ingestion_artifacts_on_failure():
    svc = FileService.__new__(FileService)
    doc = _make_file(storage_path="uploads/file.pdf")
    repo = MagicMock()
    repo.find_by_id = AsyncMock(return_value=doc)
    repo.mark_processing = AsyncMock()
    repo.mark_ready = AsyncMock()
    repo.mark_failed = AsyncMock()
    repo.find_by_id_including_deleted = AsyncMock(return_value=doc)
    svc._file_repo = repo

    ingestion = MagicMock()
    ingestion.ingest_file = AsyncMock(side_effect=RuntimeError("ingestion failed"))
    ingestion.cleanup_file_artifacts = AsyncMock()

    with patch(
        "app.modules.files.services.file_upload_service.get_ingestion_service",
        return_value=ingestion,
    ), patch("app.modules.files.services.file_upload_service.cleanup_temp_file") as cleanup_temp:
        await svc.process_file_background(
            file_id="file1",
            file_path="/tmp/file.pdf",
            display_name="Tài liệu",
        )

    ingestion.ingest_file.assert_awaited_once_with(
        file_id="file1",
        display_name="Tài liệu",
        file_path="/tmp/file.pdf",
        original_storage_path="uploads/file.pdf",
    )
    ingestion.cleanup_file_artifacts.assert_awaited_once_with("file1", "uploads/file.md")
    repo.mark_failed.assert_awaited_once_with("file1")
    repo.mark_ready.assert_not_awaited()
    cleanup_temp.assert_called_once_with("/tmp/file.pdf")
