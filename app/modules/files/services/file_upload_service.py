import os
import logging
import time
from typing import Optional, Dict, Any, Callable, Awaitable, Tuple

from app.core.config import settings
from app.core.exceptions import NotFoundException, ConflictException, ValidationException
from app.modules.files.models.file import FileDocument, FileStatus
from app.integrations.storage.client import r2_storage
from app.modules.files.utils.file_helpers import (
    validate_file_size,
    validate_file_extension,
    detect_mime_type,
    generate_storage_path,
    cleanup_temp_file,
)
from app.modules.files.utils.upload_state import UploadStep, UploadState
from app.modules.rag.ingestion.ingestion_service import get_ingestion_service
from app.utils.text_utils import remove_accents
from app.modules.metadata.services.metadata_service import get_metadata_service

logger = logging.getLogger(__name__)

class FileUploadMixin:
    """
    Mixin class handling file uploads and background processing using Beanie ODM.
    Expects to be mixed into FileService.
    """

    async def upload_file_quick(
        self,
        file_path: str,
        original_filename: str,
        display_name: Optional[str] = None,
        custom_metadata: Optional[dict] = None,
        lecturer_only: bool = False,
        progress_callback: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None,
    ) -> tuple[FileDocument, dict[str, Any]]:
        """Create DB record + upload original to R2, then return immediately with pending status."""
        start_quick = time.perf_counter()
        state, file_info = await self._prepare_upload_state(
            file_path, original_filename, display_name, custom_metadata
        )

        async def _notify(step: str, message: str):
            if progress_callback:
                await progress_callback({"step": step, "message": message, "file_id": state.file_id})

        try:
            await _notify("db_creating", "Đang tạo bản ghi file")

            _dn = display_name or original_filename
            file_doc = FileDocument(
                display_name=_dn,
                display_name_unaccented=remove_accents(_dn),
                original_filename=original_filename,
                original_filename_unaccented=remove_accents(original_filename),
                storage_path=state.storage_path,
                storage_bucket=settings.R2_BUCKET_NAME,
                file_size=file_info["file_size"],
                mime_type=file_info["mime_type"],
                custom_metadata=state.custom_metadata or {},
                status=FileStatus.UPLOADING,
                lecturer_only=lecturer_only,
            )
            await self.file_repo.create(file_doc)
            state.file_id = str(file_doc.id)
            state.mark_step(UploadStep.DB_CREATED)

            await _notify("uploading_original", "Đang upload file gốc lên storage")
            with open(file_path, "rb") as f:
                await r2_storage.upload_file(
                    file=f,
                    object_name=state.storage_path,
                    content_type=file_info["mime_type"],
                    metadata={"file_id": state.file_id},
                )
            state.mark_step(UploadStep.R2_UPLOADED)
            await _notify("queued_background", "Đã lưu file lên storage, đang xử lý nền")

            quick_dur = time.perf_counter() - start_quick
            logger.info(f"[Upload] Quick upload for {original_filename} (ID: {state.file_id}) completed in {quick_dur:.2f}s")
            
            return file_doc, {
                "file_id": state.file_id,
                "display_name": display_name or original_filename,
                "custom_metadata": state.custom_metadata or {},
                "storage_path": state.storage_path,
            }
        except Exception as e:
            await self._rollback_upload(state, str(e))
            raise

    async def process_file_background(
        self,
        file_id: str,
        file_path: str,
        display_name: str,
        custom_metadata: Optional[dict] = None,
        progress_callback: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None,
    ) -> None:
        """Continue processing after original file is stored in R2."""
        start_bg = time.perf_counter()
        async def _notify(step: str, message: str):
            if progress_callback:
                await progress_callback({"step": step, "message": message, "file_id": file_id})

        ingestion_service = None
        markdown_storage_path = None
        try:
            ingestion_service = get_ingestion_service()
            file_doc = await self.file_repo.find_by_id(file_id)
            if not file_doc:
                raise NotFoundException("File", file_id)

            storage_path = file_doc.storage_path
            markdown_storage_path = storage_path.rsplit(".", 1)[0] + ".md"

            processing_doc = await self.file_repo.mark_processing(file_id)
            if not processing_doc:
                raise NotFoundException("Active file", file_id)

            await _notify("processing", "Đang xử lý parsing, tạo TOC và lưu Corpus Tree")
            ingest_result = await ingestion_service.ingest_file(
                file_id=file_id,
                display_name=display_name,
                file_path=file_path,
                original_storage_path=storage_path,
            )
            markdown_storage_path = ingest_result.markdown_storage_path

            ready_doc = await self.file_repo.mark_ready(
                file_id=file_id,
                markdown_storage_path=ingest_result.markdown_storage_path,
                markdown_file_size=ingest_result.markdown_file_size,
                table_of_contents=ingest_result.table_of_contents,
            )
            if not ready_doc:
                raise NotFoundException("File", file_id)

            bg_dur = time.perf_counter() - start_bg
            logger.info(f"[Upload] Background processing for file {file_id} completed in {bg_dur:.2f}s")
            await _notify("completed", "Upload hoàn tất")
        except Exception as e:
            logger.error(f"Background processing failed for file {file_id}: {e}", exc_info=True)
            if ingestion_service:
                await ingestion_service.cleanup_file_artifacts(file_id, markdown_storage_path)
            current_doc = await self.file_repo.find_by_id_including_deleted(file_id)
            if current_doc and current_doc.deleted_at is not None:
                await _notify("deleted", "Tệp đã bị xóa trong khi đang xử lý")
            else:
                await self.file_repo.mark_failed(file_id)
                await _notify("failed", f"Xử lý nền thất bại: {str(e)}")
        finally:
            cleanup_temp_file(file_path)

    async def _prepare_upload_state(
        self,
        file_path: str,
        original_filename: str,
        display_name: Optional[str] = None,
        custom_metadata: Optional[dict] = None
    ) -> Tuple[UploadState, Dict[str, Any]]:
        """Step 1: Validate and prepare initial state."""
        validate_file_extension(original_filename)
        file_size = os.path.getsize(file_path)
        validate_file_size(file_size)
        mime_type = detect_mime_type(file_path)

        validator = get_metadata_service()
        is_valid, errors, meta_model = validator.validate_and_parse_file_metadata(custom_metadata or {})
        if not is_valid:
            raise ValidationException(f"Invalid metadata: {', '.join(errors)}")

        custom_metadata = meta_model.model_dump(mode="json") if meta_model else {}

        existing_file = await self.file_repo.find_by_original_filename(original_filename)
        if existing_file:
            raise ConflictException(f"File '{original_filename}' already exists")

        state = UploadState(custom_metadata=custom_metadata)
        state.storage_path = generate_storage_path(original_filename)
        state.mark_step(UploadStep.VALIDATED)

        file_info = {
            "file_size": file_size,
            "mime_type": mime_type
        }

        return state, file_info

    async def _rollback_upload(self, state: UploadState, error_msg: str) -> None:
        """Intelligent rollback based on completed steps."""
        logger.warning(f"Rolling back upload (file_id={state.file_id}): {error_msg}")

        if state.has_step(UploadStep.R2_UPLOADED) and state.storage_path:
            try:
                await r2_storage.delete_file(state.storage_path)
            except Exception as e:
                logger.warning(f"Rollback: Failed to delete Cloudflare R2 file: {e}")

        if state.has_step(UploadStep.DB_CREATED) and state.file_id:
            try:
                doc = await self.file_repo.find_by_id(state.file_id)
                if doc:
                    await self.file_repo.delete(doc)
            except Exception as e:
                logger.warning(f"Rollback: Failed to delete DB record: {e}")
