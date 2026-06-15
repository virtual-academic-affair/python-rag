import io
import os
import logging
import time
from pathlib import Path
from typing import Optional, Dict, Any, Callable, Awaitable, Tuple
from bson import ObjectId

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
from app.modules.files.toc_tree.repositories.toc_tree_repository import FileTocTreeRepository
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
            )
            await file_doc.insert()
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

        try:
            file_doc = await FileDocument.get(file_id)
            if not file_doc:
                raise NotFoundException("File", file_id)

            storage_path = file_doc.storage_path

            # Update status to processing
            file_doc.status = FileStatus.PROCESSING
            await file_doc.save()

            await _notify("processing", "Đang xử lý parsing, tạo TOC và lưu Vector DB")
            ingest_result = await self._ingest_to_vector_db(
                file_id=file_id,
                display_name=display_name,
                file_path=file_path,
                custom_metadata=custom_metadata,
            )
            
            markdown_content = ingest_result["markdown_content"]
            markdown_bytes = markdown_content.encode("utf-8")
            md_storage_path = storage_path.rsplit(".", 1)[0] + ".md"
            
            await r2_storage.upload_file(
                file=io.BytesIO(markdown_bytes),
                object_name=md_storage_path,
                content_type="text/markdown; charset=utf-8",
            )

            # Update TOC Tree with markdown storage path
            toc_repo = FileTocTreeRepository()
            await toc_repo.upsert_by_file_id(file_id, {
                "doc_name": display_name,
                "doc_description": ingest_result.get("summary", ""),
                "line_count": ingest_result.get("line_count", 0),
                "structure": ingest_result.get("toc_structure", []),
                "markdown_storage_path": md_storage_path,
            })

            # Final update atomically
            file_ready_doc = await FileDocument.find_one(
                FileDocument.id == ObjectId(file_id),
                FileDocument.status != FileStatus.READY
            )
            if file_ready_doc:
                file_ready_doc.markdown_storage_path = md_storage_path
                file_ready_doc.markdown_file_size = len(markdown_bytes)
                file_ready_doc.table_of_contents = ingest_result.get("table_of_contents", [])
                file_ready_doc.status = FileStatus.READY
                await file_ready_doc.save()
            
            bg_dur = time.perf_counter() - start_bg
            logger.info(f"[Upload] Background processing for file {file_id} completed in {bg_dur:.2f}s")
            await _notify("completed", "Upload hoàn tất")
        except Exception as e:
            logger.error(f"Background processing failed for file {file_id}: {e}", exc_info=True)
            doc_err = await FileDocument.get(file_id)
            if doc_err:
                doc_err.status = FileStatus.FAILED
                await doc_err.save()
            await _notify("failed", f"Xử lý nền thất bại: {str(e)}")
        finally:
            cleanup_temp_file(file_path)
            try:
                from app.modules.rag.ingestion.ingestion_service import get_ingestion_service
                ingest_svc = get_ingestion_service()
                await ingest_svc.cleanup_local_artifacts(file_id)
            except Exception as e:
                logger.warning(f"Failed to cleanup markdown artifacts for {file_id}: {e}")

    async def _ingest_to_vector_db(
        self,
        file_id: str,
        display_name: str,
        file_path: str,
        custom_metadata: Optional[dict] = None,
    ) -> Dict[str, Any]:
        """Helper to trigger the ingestion service for RAG."""
        from app.modules.rag.ingestion.ingestion_service import get_ingestion_service
        ingest_svc = get_ingestion_service()
        result = await ingest_svc.ingest_file(
            file_id=file_id,
            file_name=display_name,
            file_path=file_path,
            metadata=custom_metadata,
        )
        return result

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

        existing_file = await FileDocument.find_one(
            FileDocument.original_filename == original_filename
        )
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

        if state.has_step(UploadStep.MARKDOWN_GENERATED) and state.markdown_storage_path:
            try:
                await r2_storage.delete_file(state.markdown_storage_path)
            except Exception as e:
                logger.warning(f"Rollback: Failed to delete markdown artifact: {e}")

        if state.has_step(UploadStep.R2_UPLOADED) and state.storage_path:
            try:
                await r2_storage.delete_file(state.storage_path)
            except Exception as e:
                logger.warning(f"Rollback: Failed to delete Cloudflare R2 file: {e}")

        if state.has_step(UploadStep.DB_CREATED) and state.file_id:
            try:
                doc = await FileDocument.get(state.file_id)
                if doc:
                    await doc.delete()
            except Exception as e:
                logger.warning(f"Rollback: Failed to delete DB record: {e}")
