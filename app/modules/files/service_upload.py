import io
import os
import logging
import time
from pathlib import Path
from typing import Optional, Dict, Any, Callable, Awaitable, Tuple

from app.core.config import settings
from app.core.exceptions import NotFoundException, ConflictException, ValidationException
from app.modules.files.models import FileDocument, FileStatus
from app.integrations.storage.client import r2_storage
from app.modules.rag.ingestion.service import get_ingestion_service
from app.modules.files.utils import (
    validate_file_size,
    validate_file_extension,
    detect_mime_type,
    generate_storage_path,
    cleanup_temp_file,
)
from app.modules.files.upload_state import UploadStep, UploadState
from app.modules.files.toc_tree.repository import FileTocTreeRepository
from app.core.text_utils import remove_accents
from app.modules.metadata.service import get_metadata_service

logger = logging.getLogger(__name__)


class FileUploadMixin:
    """
    Mixin class handling file uploads and background processing.
    Expects to be mixed into FileService which provides `file_repo`, `metadata_svc`, and `get_file_by_id`.
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
            file_doc_data = {
                "display_name": _dn,
                "display_name_unaccented": remove_accents(_dn),
                "original_filename": original_filename,
                "original_filename_unaccented": remove_accents(original_filename),
                "storage_path": state.storage_path,
                "storage_bucket": settings.R2_BUCKET_NAME,
                "file_size": file_info["file_size"],
                "mime_type": file_info["mime_type"],
                "custom_metadata": state.custom_metadata or {},
                "status": FileStatus.UPLOADING.value,
            }
            created_file = await self.file_repo.create(file_doc_data)
            state.file_id = str(created_file["_id"])
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

            file_doc = await self.get_file_by_id(state.file_id)
            
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
            file_doc = await self.file_repo.find_by_id(file_id)
            if not file_doc:
                raise NotFoundException("File", file_id)

            storage_path = file_doc.get("storage_path")

            # Update status to processing
            await self.file_repo.update_by_id(file_id, {"status": FileStatus.PROCESSING.value})

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

            # Update TOC Tree with markdown storage path for PageIndex cache retrieval
            toc_repo = FileTocTreeRepository()
            await toc_repo.upsert_by_file_id(file_id, {
                "doc_name": display_name,
                "doc_description": ingest_result.get("summary", ""),
                "line_count": ingest_result.get("line_count", 0),
                "structure": ingest_result.get("toc_structure", []),
                "markdown_storage_path": md_storage_path,
            })

            # Final update atomically
            await self.file_repo.find_one_and_update(
                {
                    "_id": self.file_repo._to_object_id(file_id), 
                    "status": {"$ne": FileStatus.READY.value}
                },
                {
                    "markdown_storage_path": md_storage_path,
                    "markdown_file_size": len(markdown_bytes),
                    "table_of_contents": ingest_result.get("table_of_contents", []),
                    "status": FileStatus.READY.value,
                }
            )
            
            bg_dur = time.perf_counter() - start_bg
            logger.info(f"[Upload] Background processing for file {file_id} completed in {bg_dur:.2f}s")
            await _notify("completed", "Upload hoàn tất")
        except Exception as e:
            logger.error(f"Background processing failed for file {file_id}: {e}", exc_info=True)
            await self.file_repo.update_by_id(file_id, {"status": FileStatus.FAILED.value})
            await _notify("failed", f"Xử lý nền thất bại: {str(e)}")
        finally:
            cleanup_temp_file(file_path)
            try:
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
        ingest_svc = get_ingestion_service()
        result = await ingest_svc.ingest_pdf_chunks(
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
        # Validation
        validate_file_extension(original_filename)
        file_size = os.path.getsize(file_path)
        validate_file_size(file_size)
        mime_type = detect_mime_type(file_path)

        # Metadata validation and normalization using stateless validator
        validator = get_metadata_service()
        is_valid, errors, meta_model = validator.validate_and_parse_file_metadata(custom_metadata or {})
        if not is_valid:
            raise ValidationException(f"Invalid metadata: {', '.join(errors)}")

        # Use normalized metadata (with defaults) from here on
        custom_metadata = meta_model.model_dump(mode="json") if meta_model else {}

        existing_file = await self.file_repo.find_one({
            "original_filename": original_filename,
        })
        if existing_file:
            raise ConflictException(f"File '{original_filename}' already exists")

        # Prepare initial state
        state = UploadState(custom_metadata=custom_metadata)

        # Generate storage path
        state.storage_path = generate_storage_path(original_filename)
        state.mark_step(UploadStep.VALIDATED)

        file_info = {
            "file_size": file_size,
            "mime_type": mime_type
        }

        return state, file_info

    async def _rollback_upload(self, state: UploadState, error_msg: str) -> None:
        """
        Intelligent rollback based on completed steps.
        Cleans up resources in reverse order of creation.
        """
        logger.warning(f"Rolling back upload (file_id={state.file_id}): {error_msg}")

        # Rollback markdown artifact in Cloudflare R2
        if state.has_step(UploadStep.MARKDOWN_GENERATED) and state.markdown_storage_path:
            try:
                await r2_storage.delete_file(state.markdown_storage_path)
                logger.info(f"Rollback: Deleted markdown artifact {state.markdown_storage_path}")
            except Exception as e:
                logger.warning(f"Rollback: Failed to delete markdown artifact: {e}")

        # Rollback Cloudflare R2 (if uploaded)
        if state.has_step(UploadStep.R2_UPLOADED) and state.storage_path:
            try:
                await r2_storage.delete_file(state.storage_path)
                logger.info(f"Rollback: Deleted Cloudflare R2 file {state.storage_path}")
            except Exception as e:
                logger.warning(f"Rollback: Failed to delete Cloudflare R2 file: {e}")

        # Rollback DB record (if created)
        if state.has_step(UploadStep.DB_CREATED) and state.file_id:
            try:
                await self.file_repo.delete_by_id(state.file_id)
                logger.info(f"Rollback: Deleted DB record {state.file_id}")
            except Exception as e:
                logger.warning(f"Rollback: Failed to delete DB record: {e}")

