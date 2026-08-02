import io
import logging
from typing import Optional

from app.core.config import settings
from app.core.exceptions import NotFoundException, ConflictException, ValidationException
from app.modules.files.models.file import FileDocument, FileStatus
from app.modules.files.repositories.file_repository import FileRepository
from app.modules.files.dtos.ocr_review import OcrReviewResponse
from app.integrations.storage.client import r2_storage
from app.modules.files.utils.notifier import get_file_status_notifier

logger = logging.getLogger(__name__)


class OcrReviewService:
    """Service handling OCR draft review, save, approve, and reject operations for admins."""

    def __init__(self, file_repo: Optional[FileRepository] = None):
        self._file_repo = file_repo or FileRepository()

    async def get_review(self, file_id: str) -> OcrReviewResponse:
        file_doc = await self._file_repo.find_by_id(file_id)
        if not file_doc:
            raise NotFoundException("File", file_id)

        if file_doc.status != FileStatus.AWAITING_REVIEW:
            raise ConflictException(f"File status is '{file_doc.status.value}', expected 'awaiting_review'")

        if not file_doc.markdown_storage_path:
            raise ConflictException("OCR markdown draft storage path is missing")

        try:
            markdown_buf = await r2_storage.download_file(file_doc.markdown_storage_path)
            markdown_text = markdown_buf.read().decode("utf-8")
        except Exception as e:
            logger.error(f"Failed to download OCR draft for file {file_id}: {e}")
            raise ConflictException("Failed to read OCR draft from storage") from e

        return OcrReviewResponse(
            file_id=str(file_doc.id),
            status=file_doc.status.value,
            markdown=markdown_text,
            ocr_page_count=file_doc.ocr_page_count,
            ocr_completed_at=file_doc.ocr_completed_at.isoformat() if file_doc.ocr_completed_at else None,
            last_processing_error=file_doc.last_processing_error,
        )

    async def save_draft(self, file_id: str, markdown: str, client_id: Optional[str] = None) -> None:
        file_doc = await self._file_repo.find_by_id(file_id)
        if not file_doc:
            raise NotFoundException("File", file_id)

        if file_doc.status != FileStatus.AWAITING_REVIEW:
            raise ConflictException(f"File status is '{file_doc.status.value}', expected 'awaiting_review'")

        if not markdown or not markdown.strip():
            raise ValidationException("Markdown content cannot be empty")

        markdown_bytes = markdown.encode("utf-8")
        max_bytes = settings.MAX_FILE_SIZE_MB * 1024 * 1024
        if len(markdown_bytes) > max_bytes:
            raise ValidationException(
                f"Markdown draft exceeds the maximum allowed size of {settings.MAX_FILE_SIZE_MB} MB"
            )

        if not file_doc.markdown_storage_path:
            raise ConflictException("OCR markdown draft storage path is missing")
        try:
            await r2_storage.upload_file(
                file=io.BytesIO(markdown_bytes),
                object_name=file_doc.markdown_storage_path,
                content_type="text/markdown; charset=utf-8",
            )
        except Exception as e:
            logger.error(f"Failed to save updated OCR draft for file {file_id}: {e}")
            raise ConflictException("Failed to save OCR draft to storage") from e

        if client_id:
            notifier = get_file_status_notifier()
            await notifier.notify(client_id, {
                "step": "review_saved",
                "message": "Đã lưu bản chỉnh sửa OCR draft",
                "file_id": file_id,
            })

    async def approve(self, file_id: str) -> FileDocument:
        claimed_doc = await self._file_repo.claim_for_indexing(file_id)
        if not claimed_doc:
            raise ConflictException("File is not awaiting review or is already being processed")
        return claimed_doc

    async def reject(self, file_id: str) -> None:
        file_doc = await self._file_repo.find_by_id(file_id)
        if not file_doc:
            raise NotFoundException("File", file_id)

        if file_doc.status != FileStatus.AWAITING_REVIEW:
            raise ConflictException(f"File status is '{file_doc.status.value}', expected 'awaiting_review'")

        success = await self._file_repo.mark_rejected(file_id)
        if not success:
            raise ConflictException("File status changed concurrently")

        if file_doc.markdown_storage_path:
            try:
                await r2_storage.delete_file(file_doc.markdown_storage_path)
            except Exception as e:
                logger.warning(f"Failed to delete rejected markdown draft for file {file_id}: {e}")


_ocr_review_service_instance: Optional[OcrReviewService] = None


def get_ocr_review_service() -> OcrReviewService:
    global _ocr_review_service_instance
    if _ocr_review_service_instance is None:
        _ocr_review_service_instance = OcrReviewService()
    return _ocr_review_service_instance
