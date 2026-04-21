"""
File Service - Business logic for file management operations.
Handles file uploads, downloads, deletions, and integrations with Cloudflare R2 and Gemini.
"""

import asyncio
import io
import logging
import mimetypes
import os
import tempfile
import time
from pathlib import Path
from typing import Optional, BinaryIO, List, Tuple, Dict, Any, Callable, Awaitable

from app.integrations.llamaparse.client import get_llamaparse_client


# Ensure essential Office mime types are registered globally for Google GenAI SDK
# (Production environments like Docker/Alpine often lack these in /etc/mime.types)
mimetypes.add_type('application/vnd.openxmlformats-officedocument.wordprocessingml.document', '.docx')
mimetypes.add_type('application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', '.xlsx')
mimetypes.add_type('application/vnd.openxmlformats-officedocument.presentationml.presentation', '.pptx')
mimetypes.add_type('application/msword', '.doc')
mimetypes.add_type('application/vnd.ms-excel', '.xls')
mimetypes.add_type('application/pdf', '.pdf')

from app.core.config import settings
from app.core.exceptions import (
    NotFoundException,
    StorageException,
    ConflictException,
    ValidationException,
)
from app.modules.files.models import FileDocument
from app.modules.files.models import FileStatus
from app.modules.files.repository import FileRepository
from app.integrations.storage.client import r2_storage
from app.modules.rag.ingestion.service import get_ingestion_service
from app.modules.metadata.service import get_metadata_service
from app.modules.files.utils import (
    validate_file_size,
    validate_file_extension,
    detect_mime_type,
    generate_storage_path,
    cleanup_temp_file,
)
from app.modules.files.upload_state import (
    UploadStep,
    UploadState,
)


from app.integrations.qdrant.indexer import get_qdrant_indexer
from app.modules.files.toc_tree.repository import FileTocTreeRepository
from app.integrations.pageindex.client import get_page_index_client
from app.modules.metadata.utils.filter_builder import get_filter_builder

logger = logging.getLogger(__name__)




def _to_file_model(doc: dict) -> Optional[FileDocument]:
    """Convert dict to FileDocument."""
    if not doc:
        return None
    return FileDocument(**doc)


class FileService:
    """
    Service for file management operations.
    Coordinates between Cloudflare R2 storage, MongoDB, and Gemini File Search.
    """

    def __init__(self):
        """Initialize FileService with repositories."""
        self._file_repo = None
        self._metadata_svc = None

    @property
    def metadata_svc(self):
        """Lazy load metadata service."""
        if self._metadata_svc is None:
            self._metadata_svc = get_metadata_service()
        return self._metadata_svc

    @property
    def file_repo(self) -> FileRepository:
        """Lazy load file repository."""
        if self._file_repo is None:
            self._file_repo = FileRepository()
        return self._file_repo

    async def upload_file_quick(
        self,
        file_path: str,
        original_filename: str,
        display_name: Optional[str] = None,
        custom_metadata: Optional[dict] = None,
        progress_callback: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None,
    ) -> tuple[FileDocument, dict[str, Any]]:
        """Create DB record + upload original to R2, then return immediately with pending status."""
        state, file_info = await self._prepare_upload_state(
            file_path, original_filename, display_name, custom_metadata
        )

        async def _notify(step: str, message: str):
            if progress_callback:
                await progress_callback({"step": step, "message": message, "file_id": state.file_id})

        try:
            await _notify("db_creating", "Đang tạo bản ghi file")
            from app.core.text_utils import remove_accents
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
                content_type="text/markdown",
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

            # Final update
            await self.file_repo.update_by_id(
                file_id,
                {
                    "markdown_storage_path": md_storage_path,
                    "markdown_file_size": len(markdown_bytes),
                    "table_of_contents": ingest_result.get("table_of_contents", []),
                    "status": FileStatus.READY.value,
                },
            )

            if custom_metadata:
                await self.metadata_svc.sync_metadata_counters(custom_metadata, delta=1)

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

        # Metadata validation
        await self.metadata_svc.validate_file_metadata_requirements(custom_metadata)

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

        # Rollback Metadata (if synced)
        if state.has_step(UploadStep.METADATA_SYNCED) and state.custom_metadata:
            try:
                await self.metadata_svc.sync_metadata_counters(state.custom_metadata, delta=-1)
                logger.info(f"Rollback: Decremented metadata counters for {list(state.custom_metadata.keys())}")
            except Exception as e:
                logger.warning(f"Rollback: Failed to decrement metadata counters: {e}")

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


    async def download_file(self, file_id: str, user_role: Optional[str] = None) -> tuple[BinaryIO, str, str]:
        """
        Download a file from Cloudflare R2.
        If user_role is provided, validates access permissions.

        Returns:
            tuple: (file_object, filename, mime_type)
        """
        # Reuse get_file_by_id for database fetching and permission check
        file_doc = await self.get_file_by_id(file_id, user_role=user_role)
        if not file_doc:
            raise NotFoundException("File", file_id)

        try:
            file_obj = await r2_storage.download_file(file_doc.storage_path)
            return file_obj, file_doc.original_filename, file_doc.mime_type
        except Exception as e:
            logger.error(f"Download failed for {file_id}: {e}", exc_info=True)
            raise StorageException(f"File download failed: {str(e)}")


    async def delete_file(self, file_id: str) -> bool:
        """Delete a file (hard delete)."""
        file_doc = await self.file_repo.find_by_id(file_id)
        if not file_doc:
            raise NotFoundException("File", file_id)

        # Delete from Cloudflare R2
        if storage_path := file_doc.get("storage_path"):
            try:
                await r2_storage.delete_file(storage_path)
            except Exception as e:
                logger.warning(f"Failed to delete from Cloudflare R2: {e}")

        # Xóa Qdrant
        indexer = get_qdrant_indexer()
        await indexer.delete_by_file_id(file_id)

        # Xóa file_toc_trees
        toc_repo = FileTocTreeRepository()
        await toc_repo.delete_by_file_id(file_id)

        # Xóa cache PageIndex (Redis + local .md file)
        page_index_client = get_page_index_client()
        await page_index_client.evict_doc(file_id)

        # Hard delete from MongoDB
        await self.file_repo.delete_by_id(file_id)

        # Decrement metadata counters if the file was active and has custom_metadata
        if file_doc.get("status") == FileStatus.READY.value and file_doc.get("custom_metadata"):
            await self.metadata_svc.sync_metadata_counters(file_doc["custom_metadata"], delta=-1)

        logger.info(f"File {file_id} deleted")
        return True

    async def update_file_display_name(self, file_id: str, new_display_name: str) -> Optional[FileDocument]:
        """Update the display name of a file."""
        file_doc_dict = await self.file_repo.find_by_id(file_id)
        if not file_doc_dict:
            raise NotFoundException("File", file_id)

        from app.core.text_utils import remove_accents
        update_data = {
            "display_name": new_display_name,
            "display_name_unaccented": remove_accents(new_display_name),
        }
        update_success = await self.file_repo.update_by_id(file_id, update_data)

        if update_success:
            file_doc_dict["display_name"] = new_display_name
            return _to_file_model(file_doc_dict)
        return None

    async def _apply_role_filters_and_metadata_masking(self, files: List[Dict[str, Any]], user_role: str) -> List[Dict[str, Any]]:
        """
        Centrally handles both access permission filtering (access_scope)
        and custom_metadata masking (visible_roles).
        """
        if not files or not user_role:
            return files

        # 1. Filter by access_scope (scope empty means internal file => admin only)
        if user_role == "student":
            files = [
                f for f in files
                if "student" in ((f.get("custom_metadata") or {}).get("access_scope") or [])
            ]
        elif user_role == "lecture":
            files = [
                f for f in files
                if "lecture" in ((f.get("custom_metadata") or {}).get("access_scope") or [])
            ]
        # Admin sees all, no filter needed

        # 2. Mask custom_metadata based on visible_roles via MetadataService
        await self.metadata_svc.filter_custom_metadata_by_role(files, user_role)

        return files



    async def list_files(
        self,
        status: Optional[FileStatus] = None,
        custom_metadata_filter: Optional[Dict[str, Any]] = None,
        keywords: Optional[str] = None,
        user_role: str = "student",
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[list[FileDocument], int]:
        """List files with optional filters and role-based access control."""
        filters = {}
        if status:
            filters["status"] = status.value

        # Keyword search: match against unaccented field (user may type with/without accents)
        if keywords:
            from app.core.text_utils import remove_accents
            unaccented_kw = remove_accents(keywords)
            filters["$or"] = [
                {"display_name_unaccented": {"$regex": unaccented_kw, "$options": "i"}},
                {"original_filename_unaccented": {"$regex": unaccented_kw, "$options": "i"}}
            ]

        # Add metadata filters with "all" support
        builder = get_filter_builder()
        mongo_filter = await builder.build_mongo_filter(
            metadata=custom_metadata_filter or {},
            user_role=user_role,
            skip_validation=True # Validation happens elsewhere or is implied
        )
        
        # Safe merge: prevent $or key collision when combining keyword filter with mongo_filter
        if mongo_filter:
            keyword_or = filters.pop("$or", None)
            filters.update(mongo_filter)
            if keyword_or:
                # Wrap keyword $or inside $and so it doesn't get overwritten
                filters["$and"] = filters.get("$and", []) + [{"$or": keyword_or}]

        # Add role-based access filtering directly to DB query (Fix pagination)
        if user_role == "student":
            filters["custom_metadata.access_scope"] = "student"
        elif user_role == "lecture":
            filters["custom_metadata.access_scope"] = "lecture"
        # Admin sees all, no filter needed

        file_dicts = await self.file_repo.find_many(filters, skip, limit, sort=[("created_at", -1)])
        total = await self.file_repo.count(filters)

        # Apply metadata masking (visible_roles), access filtering is now handled by the DB
        await self.metadata_svc.filter_custom_metadata_by_role(file_dicts, user_role)

        files = [_to_file_model(f) for f in file_dicts]
        return files, total

    async def get_file_by_id(self, file_id: str, user_role: Optional[str] = None) -> Optional[FileDocument]:
        """
        Get a single file by ID.
        If user_role is provided, validates access permissions and masks metadata.
        """
        file_dict = await self.file_repo.find_by_id(file_id)
        if not file_dict:
            return None

        if user_role:
            # _apply_role_filters_and_metadata_masking expects a list and returns a filtered list
            filtered_files = await self._apply_role_filters_and_metadata_masking([file_dict], user_role)
            if not filtered_files:
                # If the file was filtered out due to access_scope, it's not found for this user
                return None
            file_dict = filtered_files[0]

        return _to_file_model(file_dict)

    async def get_file_data(self, file_id: str, user_role: str = "student") -> tuple[Any, FileDocument]:
        """Get file bytes and document for download."""
        file_doc_dict = await self.file_repo.find_by_id(file_id)
        if not file_doc_dict:
            raise NotFoundException("File", file_id)

        # Apply role filtering to verify access
        filtered_files = await self._apply_role_filters_and_metadata_masking([file_doc_dict], user_role)
        if not filtered_files:
            raise NotFoundException("File access denied", file_id)

        file_doc = _to_file_model(filtered_files[0])
        
        from app.integrations.storage.client import r2_storage
        file_data = await r2_storage.download_file(file_doc.storage_path)
        
        return file_data, file_doc


# Factory function for dependency injection
_file_service_instance: Optional["FileService"] = None


def get_file_service() -> FileService:
    """Get singleton FileService instance."""
    global _file_service_instance
    if _file_service_instance is None:
        _file_service_instance = FileService()
    return _file_service_instance
