import io
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from app.core.exceptions import ConflictException, ValidationException
from app.modules.files.models.file import FileDocument, FileStatus
from app.modules.files.services.ocr_review_service import OcrReviewService
from app.modules.files.services.file_service import FileService


def _file(**overrides):
    values = {
        "id": "64f1a2b3c4d5e6f7a8b9c0d1",
        "display_name": "Quy chế đào tạo",
        "original_filename": "quy-che.pdf",
        "storage_path": "uploads/quy-che.pdf",
        "markdown_storage_path": "uploads/quy-che.md",
        "storage_bucket": "bucket",
        "file_size": 1024,
        "mime_type": "application/pdf",
        "status": FileStatus.AWAITING_REVIEW,
        "table_of_contents": [],
        "ocr_page_count": 5,
        "deleted_at": None,
    }
    values.update(overrides)
    return FileDocument.model_construct(**values)


@pytest.mark.asyncio
async def test_get_review_success():
    repo = MagicMock()
    doc = _file(status=FileStatus.AWAITING_REVIEW)
    repo.find_by_id = AsyncMock(return_value=doc)

    service = OcrReviewService(file_repo=repo)
    # download_file returns io.BytesIO — must match real R2 client return type
    with patch(
        "app.modules.files.services.ocr_review_service.r2_storage.download_file",
        new=AsyncMock(return_value=io.BytesIO(b"# Draft content")),
    ):
        res = await service.get_review("64f1a2b3c4d5e6f7a8b9c0d1")
        assert res.file_id == "64f1a2b3c4d5e6f7a8b9c0d1"
        assert res.status == "awaiting_review"
        assert res.markdown == "# Draft content"
        assert res.ocr_page_count == 5


@pytest.mark.asyncio
async def test_get_review_wrong_status_raises_conflict():
    repo = MagicMock()
    doc = _file(status=FileStatus.READY)
    repo.find_by_id = AsyncMock(return_value=doc)

    service = OcrReviewService(file_repo=repo)
    with pytest.raises(ConflictException) as exc_info:
        await service.get_review("64f1a2b3c4d5e6f7a8b9c0d1")
    assert "awaiting_review" in str(exc_info.value)


@pytest.mark.asyncio
async def test_save_draft_success():
    repo = MagicMock()
    doc = _file(status=FileStatus.AWAITING_REVIEW)
    repo.find_by_id = AsyncMock(return_value=doc)

    service = OcrReviewService(file_repo=repo)
    with patch("app.modules.files.services.ocr_review_service.r2_storage.upload_file", new=AsyncMock()) as mock_upload:
        await service.save_draft("64f1a2b3c4d5e6f7a8b9c0d1", "# Updated Markdown Draft")
        mock_upload.assert_called_once()


@pytest.mark.asyncio
async def test_save_draft_empty_raises_validation():
    repo = MagicMock()
    doc = _file(status=FileStatus.AWAITING_REVIEW)
    repo.find_by_id = AsyncMock(return_value=doc)

    service = OcrReviewService(file_repo=repo)
    with pytest.raises(ValidationException):
        await service.save_draft("64f1a2b3c4d5e6f7a8b9c0d1", "   ")


@pytest.mark.asyncio
async def test_save_draft_exceeds_max_size_raises_validation():
    repo = MagicMock()
    doc = _file(status=FileStatus.AWAITING_REVIEW)
    repo.find_by_id = AsyncMock(return_value=doc)

    # Patch MAX_FILE_SIZE_MB=1 and send a 2 MB payload
    oversized_markdown = "a" * (2 * 1024 * 1024)
    service = OcrReviewService(file_repo=repo)
    with patch("app.modules.files.services.ocr_review_service.settings") as mock_settings:
        mock_settings.MAX_FILE_SIZE_MB = 1
        with pytest.raises(ValidationException, match="exceeds the maximum"):
            await service.save_draft("64f1a2b3c4d5e6f7a8b9c0d1", oversized_markdown)


@pytest.mark.asyncio
async def test_approve_claim_success():
    repo = MagicMock()
    doc = _file(status=FileStatus.PROCESSING)
    repo.claim_for_indexing = AsyncMock(return_value=doc)

    service = OcrReviewService(file_repo=repo)
    res = await service.approve("64f1a2b3c4d5e6f7a8b9c0d1")
    assert res.status == FileStatus.PROCESSING
    repo.claim_for_indexing.assert_called_once_with("64f1a2b3c4d5e6f7a8b9c0d1")


@pytest.mark.asyncio
async def test_approve_already_claimed_raises_conflict():
    repo = MagicMock()
    repo.claim_for_indexing = AsyncMock(return_value=None)

    service = OcrReviewService(file_repo=repo)
    with pytest.raises(ConflictException):
        await service.approve("64f1a2b3c4d5e6f7a8b9c0d1")


@pytest.mark.asyncio
async def test_reject_success():
    repo = MagicMock()
    doc = _file(status=FileStatus.AWAITING_REVIEW)
    repo.find_by_id = AsyncMock(return_value=doc)
    repo.mark_rejected = AsyncMock(return_value=True)

    service = OcrReviewService(file_repo=repo)
    with patch("app.modules.files.services.ocr_review_service.r2_storage.delete_file", new=AsyncMock()) as mock_delete:
        await service.reject("64f1a2b3c4d5e6f7a8b9c0d1")
        mock_delete.assert_called_once_with("uploads/quy-che.md")


@pytest.mark.asyncio
async def test_restore_awaiting_review_file_checks_draft_exists():
    service = FileService()
    doc = _file(status=FileStatus.AWAITING_REVIEW, deleted_at="2026-08-02T12:00:00Z")
    repo = MagicMock()
    repo.find_by_id_including_deleted = AsyncMock(return_value=doc)
    repo.find_by_original_filename = AsyncMock(return_value=None)
    repo.restore = AsyncMock(return_value=True)
    repo.find_by_id = AsyncMock(return_value=doc)
    service._file_repo = repo

    with patch("app.modules.files.services.file_service.r2_storage.file_exists", new=AsyncMock(side_effect=[True, True])):
        with patch("app.modules.files.services.file_service.get_rag_cache_service", return_value=MagicMock(invalidate_file=AsyncMock(), bump_file_eligibility_revision=AsyncMock())):
            restored = await service.restore_file("64f1a2b3c4d5e6f7a8b9c0d1")
            assert restored.status == FileStatus.AWAITING_REVIEW
