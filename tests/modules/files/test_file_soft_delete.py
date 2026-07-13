from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import ConflictException
from app.modules.files.models.file import FileDocument, FileStatus
from app.modules.files.repositories.file_repository import FileRepository
from app.modules.files.services.file_service import FileService


def _file(**overrides):
    values = {
        "id": "file1",
        "display_name": "Quy chế",
        "original_filename": "quy-che.pdf",
        "storage_path": "uploads/quy-che.pdf",
        "markdown_storage_path": "uploads/quy-che.md",
        "storage_bucket": "bucket",
        "file_size": 10,
        "mime_type": "application/pdf",
        "status": FileStatus.READY,
        "table_of_contents": ["Mục 1"],
        "deleted_at": None,
        "deleted_by": None,
        "deleted_corpus_node_keys": [],
    }
    values.update(overrides)
    return FileDocument.model_construct(**values)


def test_file_active_query_always_requires_deleted_at_null():
    assert FileRepository._active_query() == {"deleted_at": None}
    assert FileRepository._active_query({"status": FileStatus.READY}) == {
        "$and": [{"deleted_at": None}, {"status": FileStatus.READY}]
    }


@pytest.mark.asyncio
async def test_delete_file_soft_deletes_and_keeps_artifacts():
    service = FileService()
    doc = _file()
    repo = MagicMock()
    repo.find_by_id_including_deleted = AsyncMock(return_value=doc)
    repo.soft_delete = AsyncMock(return_value=True)
    service._file_repo = repo

    corpus = MagicMock()
    corpus.get_payload_node_keys = AsyncMock(return_value=["regulations"])
    linker = MagicMock()
    linker.unindex_file = AsyncMock()
    pageindex = MagicMock()
    pageindex.evict_doc = AsyncMock()

    with patch("app.modules.corpus.services.corpus_service.get_corpus_service", return_value=corpus), patch(
        "app.modules.files.services.file_service.get_corpus_linker", return_value=linker
    ), patch("app.integrations.pageindex.client.get_page_index_client", return_value=pageindex), patch(
        "app.modules.files.services.file_service.r2_storage.delete_file", new=AsyncMock()
    ) as delete_r2:
        assert await service.delete_file("file1", "admin1") is True

    repo.soft_delete.assert_awaited_once_with(
        "file1",
        deleted_by="admin1",
        corpus_node_keys=["regulations"],
        force_failed=False,
    )
    linker.unindex_file.assert_awaited_once_with("file1")
    pageindex.evict_doc.assert_awaited_once_with("file1")
    delete_r2.assert_not_awaited()


@pytest.mark.asyncio
async def test_restore_file_rejects_duplicate_active_filename():
    service = FileService()
    deleted = _file(deleted_at=SimpleNamespace())
    repo = MagicMock()
    repo.find_by_id_including_deleted = AsyncMock(return_value=deleted)
    repo.find_by_original_filename = AsyncMock(return_value=_file(id="file2"))
    service._file_repo = repo

    with pytest.raises(ConflictException, match="already exists"):
        await service.restore_file("file1")


@pytest.mark.asyncio
async def test_purge_file_deletes_mongo_last():
    service = FileService()
    deleted = _file(deleted_at=SimpleNamespace())
    repo = MagicMock()
    repo.find_by_id_including_deleted = AsyncMock(return_value=deleted)
    repo.delete = AsyncMock()
    service._file_repo = repo

    linker = MagicMock()
    linker.unindex_file = AsyncMock()
    pageindex = MagicMock()
    pageindex.evict_doc = AsyncMock()
    toc_repo = MagicMock()
    toc_repo.delete_by_file_id = AsyncMock()

    with patch("app.modules.files.services.file_service.get_corpus_linker", return_value=linker), patch(
        "app.integrations.pageindex.client.get_page_index_client", return_value=pageindex
    ), patch("app.modules.files.services.file_service.FileTocTreeRepository", return_value=toc_repo), patch(
        "app.modules.files.services.file_service.r2_storage.delete_file", new=AsyncMock(return_value=True)
    ) as delete_r2:
        assert await service.purge_file("file1") is True

    assert delete_r2.await_count == 2
    repo.delete.assert_awaited_once_with(deleted)
