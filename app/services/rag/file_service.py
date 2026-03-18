"""
File Service - Business logic for file management operations.
Handles file uploads, downloads, deletions, and integrations with MinIO and Gemini.
"""

import asyncio
import logging
import time
from enum import Enum
from pathlib import Path
from typing import Optional, BinaryIO
from dataclasses import dataclass, field

from app.core.config import settings
from app.core.exceptions import (
    NotFoundException,
    StorageException,
    GeminiException,
    ConflictException,
    ValidationException,
)
from app.models.database import FileDocument
from app.models.enums import FileStatus
from app.repositories.file_repository import FileRepository
from app.repositories.store_repository import StoreRepository
from app.storage.minio_client import minio_storage
from app.services.rag.utils.file_utils import (
    validate_file_size,
    validate_file_extension,
    detect_mime_type,
    generate_storage_path,
)

logger = logging.getLogger(__name__)


class UploadStep(Enum):
    """Steps in the upload process for tracking rollback."""
    VALIDATED = "validated"
    DB_CREATED = "db_created"
    MINIO_UPLOADED = "minio_uploaded"
    GEMINI_UPLOADED = "gemini_uploaded"
    COMPLETED = "completed"


@dataclass
class UploadState:
    """
    Track upload progress for intelligent rollback.
    Each step completed is recorded to enable precise cleanup on failure.
    """
    file_id: Optional[str] = None
    storage_path: Optional[str] = None
    gemini_document_name: Optional[str] = None
    completed_steps: list = field(default_factory=list)
    
    def mark_step(self, step: UploadStep):
        """Record a completed step."""
        self.completed_steps.append(step)
    
    def has_step(self, step: UploadStep) -> bool:
        """Check if a step was completed."""
        return step in self.completed_steps


@dataclass
class GeminiFile:
    """Result from Gemini upload."""
    name: str
    uri: Optional[str] = None


def _to_file_model(doc: dict) -> Optional[FileDocument]:
    """Convert dict to FileDocument."""
    if not doc:
        return None
    return FileDocument(**doc)


class FileService:
    """
    Service for file management operations.
    Coordinates between MinIO storage, MongoDB, and Gemini File Search.
    """
    
    def __init__(self):
        """Initialize FileService with repositories and Gemini client."""
        self._file_repo = None
        self._store_repo = None
        self._gemini_client = None
    
    @property
    def file_repo(self) -> FileRepository:
        """Lazy load file repository."""
        if self._file_repo is None:
            self._file_repo = FileRepository()
        return self._file_repo
    
    @property
    def store_repo(self) -> StoreRepository:
        """Lazy load store repository."""
        if self._store_repo is None:
            self._store_repo = StoreRepository()
        return self._store_repo

    @property
    def gemini_client(self):
        """Share Gemini client from GeminiClient singleton."""
        if self._gemini_client is None:
            from app.services.rag.gemini_client import gemini_client
            self._gemini_client = gemini_client.client
        return self._gemini_client
    
    async def _validate_metadata(self, custom_metadata: dict) -> None:
        """
        Validate custom metadata against registered metadata types.
        Rules:
        - access_scope is required.
        - At least one of academic_year or cohort is required.
        """
        if not custom_metadata:
            raise ValidationException(
                "Metadata is required. Must include 'access_scope' and at least one of 'academic_year' or 'cohort'."
            )

        # Required field check
        if "access_scope" not in custom_metadata:
            raise ValidationException("Metadata 'access_scope' is required.")

        if "academic_year" not in custom_metadata and "cohort" not in custom_metadata:
            raise ValidationException(
                "Metadata must include at least one of 'academic_year' or 'cohort'."
            )

        # Value validation against registered metadata types
        from app.services.rag.metadata_service import get_metadata_service
        metadata_service = get_metadata_service()
        is_valid, errors = await metadata_service.validate_metadata(custom_metadata)

        if not is_valid:
            error_msg = "; ".join(errors)
            raise ValidationException(f"Metadata validation failed: {error_msg}")
    
    def _convert_metadata_for_gemini(self, custom_metadata: dict) -> list[dict]:
        """Convert custom_metadata dict to Gemini CustomMetadata format."""
        if not custom_metadata:
            return []
        
        result = []
        for key, value in custom_metadata.items():
            if isinstance(value, str):
                result.append({"key": key, "stringValue": value})
            elif isinstance(value, (int, float)):
                result.append({"key": key, "numericValue": value})
            elif isinstance(value, list):
                result.append({"key": key, "stringListValue": {"values": value}})
        return result
    
    async def upload_file(
        self,
        file_path: str,
        original_filename: str,
        store_id: str,
        store_name: str,
        display_name: Optional[str] = None,
        custom_metadata: Optional[dict] = None,
        enable_chunking: Optional[bool] = None,
    ) -> FileDocument:
        """
        Upload a file to MinIO and Gemini File Search (always synchronous).

        Waits for both MinIO and Gemini to complete before returning.
        Returns FileDocument with status='active' on success.

        Args:
            file_path: Path to temporary file
            original_filename: Original filename from upload
            store_id: Target store ID (MongoDB ObjectId)
            store_name: Target Gemini store name (fileSearchStores/xxx)
            display_name: Optional display name for the file
            custom_metadata: Optional metadata dict (must include access_scope
                             and at least one of academic_year/cohort)
            enable_chunking: Enable custom chunking config

        Returns:
            FileDocument: Created file document with status='active'
        """
        state = UploadState()
        
        try:
            # === STEP 1: Validation (fast, fail-fast) ===
            file_size = Path(file_path).stat().st_size
            validate_file_size(file_size)
            validate_file_extension(original_filename)
            await self._validate_metadata(custom_metadata)
            
            existing_file = await self.file_repo.find_one({
                "store_id": store_id,
                "original_filename": original_filename,
            })
            if existing_file:
                raise ConflictException(f"File '{original_filename}' already exists in store")
            
            storage_path = generate_storage_path(store_name, original_filename)
            mime_type = detect_mime_type(file_path)
            state.storage_path = storage_path
            state.mark_step(UploadStep.VALIDATED)
            
            # === STEP 2: Create DB record ===
            file_doc_data = {
                "store_id": store_id,
                "display_name": display_name or original_filename,
                "original_filename": original_filename,
                "storage_path": storage_path,
                "storage_bucket": settings.MINIO_BUCKET_NAME,
                "file_size": file_size,
                "mime_type": mime_type,
                "gemini_document_name": None,
                "custom_metadata": custom_metadata or {},
                "status": FileStatus.UPLOADING.value,
            }
            
            created_file = await self.file_repo.create(file_doc_data)
            file_id = str(created_file["_id"])
            state.file_id = file_id
            state.mark_step(UploadStep.DB_CREATED)
            
            # === STEP 3: Upload to MinIO (synchronous, fast) ===
            logger.info(f"[{file_id}] Uploading to MinIO: {storage_path}")
            with open(file_path, "rb") as f:
                await minio_storage.upload_file(
                    file=f,
                    object_name=storage_path,
                    content_type=mime_type,
                    metadata={"file_id": file_id, "store_id": store_id},
                )
            state.mark_step(UploadStep.MINIO_UPLOADED)
            
            # === STEP 4: Gemini upload (always synchronous) ===
            await self.file_repo.update_by_id(file_id, {"status": FileStatus.PROCESSING.value})
            await self._process_gemini_upload(
                file_id, file_path, display_name or original_filename,
                store_id, store_name, custom_metadata, enable_chunking, state
            )
            
            file_dict = await self.file_repo.find_by_id(file_id)
            return _to_file_model(file_dict)
            
        except Exception as e:
            await self._rollback_upload(state, str(e))
            raise
    
    async def _process_gemini_upload(
        self,
        file_id: str,
        file_path: str,
        display_name: str,
        store_id: str,
        store_name: str,
        custom_metadata: Optional[dict],
        enable_chunking: Optional[bool],
        state: UploadState,
    ) -> None:
        """Process Gemini upload (used by both sync and async modes)."""
        logger.info(f"[{file_id}] Processing Gemini upload")
        
        gemini_file = await self._upload_to_gemini(
            file_path, display_name, store_name, custom_metadata, enable_chunking
        )
        state.gemini_document_name = gemini_file.name
        state.mark_step(UploadStep.GEMINI_UPLOADED)
        
        await self.file_repo.update_by_id(
            file_id,
            {
                "gemini_document_name": gemini_file.name,
                "status": FileStatus.ACTIVE.value,
            }
        )
        
        await self._sync_store_stats(store_name, store_id)
        state.mark_step(UploadStep.COMPLETED)
        logger.info(f"[{file_id}] Upload completed successfully")
    
    async def _process_gemini_upload_safe(
        self,
        file_id: str,
        file_path: str,
        display_name: str,
        store_id: str,
        store_name: str,
        custom_metadata: Optional[dict],
        enable_chunking: Optional[bool],
        state: UploadState,
    ) -> None:
        """
        Safe wrapper for background Gemini upload.
        Handles errors gracefully without crashing the main process.
        Cleans up temp file after completion.
        """
        try:
            await self._process_gemini_upload(
                file_id, file_path, display_name, store_id, store_name,
                custom_metadata, enable_chunking, state
            )
        except Exception as e:
            logger.error(f"[{file_id}] Background Gemini upload failed: {e}", exc_info=True)
            # Mark as failed but keep MinIO file (can retry later)
            try:
                await self.file_repo.update_by_id(
                    file_id,
                    {"status": FileStatus.FAILED.value}
                )
            except Exception as db_err:
                logger.error(f"[{file_id}] Failed to update status: {db_err}")
        finally:
            # Cleanup temp file after background task completes
            self._cleanup_temp_file(file_path)
    
    def _cleanup_temp_file(self, file_path: str) -> None:
        """Safely cleanup temporary file."""
        try:
            import os
            if file_path and os.path.exists(file_path):
                os.unlink(file_path)
                logger.debug(f"Cleaned up temp file: {file_path}")
        except Exception as e:
            logger.warning(f"Failed to cleanup temp file {file_path}: {e}")
    
    async def _rollback_upload(self, state: UploadState, error_msg: str) -> None:
        """
        Intelligent rollback based on completed steps.
        Cleans up resources in reverse order of creation.
        """
        logger.warning(f"Rolling back upload (file_id={state.file_id}): {error_msg}")
        
        # Rollback Gemini (if uploaded)
        if state.has_step(UploadStep.GEMINI_UPLOADED) and state.gemini_document_name:
            try:
                await asyncio.to_thread(
                    self.gemini_client.file_search_stores.documents.delete,
                    name=state.gemini_document_name,
                    config={"force": True}
                )
                logger.info(f"Rollback: Deleted Gemini document {state.gemini_document_name}")
            except Exception as e:
                logger.warning(f"Rollback: Failed to delete Gemini document: {e}")
        
        # Rollback MinIO (if uploaded)
        if state.has_step(UploadStep.MINIO_UPLOADED) and state.storage_path:
            try:
                await minio_storage.delete_file(state.storage_path)
                logger.info(f"Rollback: Deleted MinIO file {state.storage_path}")
            except Exception as e:
                logger.warning(f"Rollback: Failed to delete MinIO file: {e}")
        
        # Rollback DB record (if created)
        if state.has_step(UploadStep.DB_CREATED) and state.file_id:
            try:
                await self.file_repo.delete_by_id(state.file_id)
                logger.info(f"Rollback: Deleted DB record {state.file_id}")
            except Exception as e:
                logger.warning(f"Rollback: Failed to delete DB record: {e}")

    async def _upload_to_gemini(
        self,
        file_path: str,
        display_name: str,
        store_name: str,
        custom_metadata: Optional[dict] = None,
        enable_chunking: Optional[bool] = None,
    ) -> GeminiFile:
        """Upload file directly to Gemini File Search store."""
        try:
            # Prepare config
            config = {"display_name": display_name}
            
            # Add custom metadata
            if custom_metadata:
                config["custom_metadata"] = self._convert_metadata_for_gemini(custom_metadata)
            
            # Add chunking config if enabled
            if enable_chunking or (enable_chunking is None and settings.CHUNKING_ENABLED):
                config["chunking_config"] = {
                    "white_space_config": {
                        "max_tokens_per_chunk": settings.CHUNKING_MAX_TOKENS_PER_CHUNK,
                        "max_overlap_tokens": settings.CHUNKING_MAX_OVERLAP_TOKENS,
                    }
                }
            
            # Upload file directly to store
            logger.info(f"Uploading to Gemini store {store_name}: {display_name}")
            operation = await asyncio.to_thread(
                self.gemini_client.file_search_stores.upload_to_file_search_store,
                file=file_path,
                file_search_store_name=store_name,
                config=config,
            )
            
            # Wait for processing with timeout
            document_name = await self._wait_for_operation(operation, display_name, store_name)
            
            logger.info(f"File uploaded to Gemini: {document_name}")
            return GeminiFile(name=document_name)
            
        except GeminiException:
            raise
        except Exception as e:
            logger.error(f"Gemini upload failed: {e}", exc_info=True)
            raise GeminiException(f"Gemini upload failed: {str(e)}")
    
    async def _wait_for_operation(self, operation, display_name: str, store_name: str, timeout: int = 120) -> str:
        """Wait for Gemini operation to complete and extract document name."""
        start_time = time.time()
        
        while not operation.done:
            if time.time() - start_time > timeout:
                raise GeminiException(f"Upload timeout after {timeout}s")
            await asyncio.sleep(2)
            operation = await asyncio.to_thread(self.gemini_client.operations.get, operation)
        
        if hasattr(operation, "error") and operation.error:
            raise GeminiException(f"Upload failed: {operation.error}")
        
        # Extract document name
        document_name = (
            getattr(getattr(operation, "result", None), "name", None) or
            getattr(getattr(operation, "response", None), "name", None)
        )
        
        # Fallback: list documents to find by display_name
        if not document_name:
            document_name = await self._find_document_by_name(store_name, display_name)
        
        if not document_name:
            raise GeminiException("Could not determine document name after upload")
        
        return document_name
    
    async def _find_document_by_name(self, store_name: str, display_name: str) -> Optional[str]:
        """Find document in store by display name."""
        docs = list(await asyncio.to_thread(
            self.gemini_client.file_search_stores.documents.list,
            parent=store_name
        ))
        for doc in docs:
            if getattr(doc, "display_name", None) == display_name:
                return doc.name
        return docs[-1].name if docs else None
    
    async def download_file(self, file_id: str) -> tuple[BinaryIO, str, str]:
        """
        Download a file from MinIO.
        
        Returns:
            tuple: (file_object, filename, mime_type)
        """
        file_dict = await self.file_repo.find_by_id(file_id)
        if not file_dict:
            raise NotFoundException("File", file_id)
        
        try:
            file_obj = await minio_storage.download_file(file_dict["storage_path"])
            return file_obj, file_dict["original_filename"], file_dict["mime_type"]
        except Exception as e:
            logger.error(f"Download failed for {file_id}: {e}", exc_info=True)
            raise StorageException(f"File download failed: {str(e)}")
    
    async def retry_failed_upload(self, file_id: str) -> FileDocument:
        """
        Retry uploading a failed file to Gemini (always synchronous).

        The file must already be in MinIO (status=FAILED).

        Args:
            file_id: ID of the failed file

        Returns:
            FileDocument: Updated file document with status='active'
        """
        file_dict = await self.file_repo.find_by_id(file_id)
        if not file_dict:
            raise NotFoundException("File", file_id)
        
        status = file_dict.get("status")
        if status not in [FileStatus.FAILED.value, "failed"]:
            raise ValidationException(f"Can only retry failed files. Current status: {status}")
        
        # Get store info
        store_id = file_dict["store_id"]
        store_dict = await self.store_repo.find_by_id(store_id)
        if not store_dict:
            raise NotFoundException("Store", store_id)
        
        store_name = store_dict["store_name"]
        storage_path = file_dict["storage_path"]
        display_name = file_dict["display_name"]
        custom_metadata = file_dict.get("custom_metadata", {})
        
        state = UploadState(file_id=file_id, storage_path=storage_path)
        state.mark_step(UploadStep.DB_CREATED)
        state.mark_step(UploadStep.MINIO_UPLOADED)
        
        # Download from MinIO to temp file
        import tempfile
        import os
        
        temp_file_path = None
        try:
            file_obj = await minio_storage.download_file(storage_path)
            
            # Write to temp file
            suffix = os.path.splitext(file_dict["original_filename"])[1]
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
                temp_file.write(file_obj.read())
                temp_file_path = temp_file.name
            
            # Update status to processing
            await self.file_repo.update_by_id(file_id, {
                "status": FileStatus.PROCESSING.value,
            })
            
            await self._process_gemini_upload(
                file_id, temp_file_path, display_name,
                store_id, store_name, custom_metadata, None, state
            )
            self._cleanup_temp_file(temp_file_path)
            
            file_dict = await self.file_repo.find_by_id(file_id)
            return _to_file_model(file_dict)
            
        except Exception as e:
            logger.error(f"Retry failed for {file_id}: {e}", exc_info=True)
            await self.file_repo.update_by_id(file_id, {
                "status": FileStatus.FAILED.value,
            })
            if temp_file_path:
                self._cleanup_temp_file(temp_file_path)
            raise StorageException(f"Retry failed: {str(e)}")

    async def delete_file(self, file_id: str) -> bool:
        """Delete a file (hard delete)."""
        file_doc = await self.file_repo.find_by_id(file_id)
        if not file_doc:
            raise NotFoundException("File", file_id)
        
        gemini_document_name = file_doc.get("gemini_document_name")
        store_id = file_doc.get("store_id")
        
        # Delete from MinIO
        if storage_path := file_doc.get("storage_path"):
            try:
                await minio_storage.delete_file(storage_path)
            except Exception as e:
                logger.warning(f"Failed to delete from MinIO: {e}")
        
        # Delete from Gemini
        if gemini_document_name:
            try:
                await asyncio.to_thread(
                    self.gemini_client.file_search_stores.documents.delete,
                    name=gemini_document_name,
                    config={"force": True}
                )
            except Exception as e:
                logger.warning(f"Failed to delete from Gemini: {e}")
        
        # Hard delete from MongoDB
        await self.file_repo.delete_by_id(file_id)
        
        # Sync store stats
        if store_id:
            await self._sync_store_stats_by_id(store_id)
        
        logger.info(f"File {file_id} deleted")
        return True
    
    async def list_files(
        self,
        store_id: Optional[str] = None,
        status: Optional[FileStatus] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[list[FileDocument], int]:
        """List files with optional filters."""
        filters = {}
        if store_id:
            filters["store_id"] = store_id
        if status:
            filters["status"] = status.value
        
        file_dicts = await self.file_repo.find_many(filters, skip, limit, sort=[("created_at", -1)])
        total = await self.file_repo.count(filters)
        
        files = [_to_file_model(f) for f in file_dicts]
        return files, total
    
    async def get_file_by_id(self, file_id: str) -> Optional[FileDocument]:
        """Get a single file by ID."""
        file_dict = await self.file_repo.find_by_id(file_id)
        return _to_file_model(file_dict)
    
    async def list_gemini_documents(self, store_name: str) -> list[dict]:
        """
        List documents directly from Gemini File Search API.
        
        Args:
            store_name: Gemini store name (fileSearchStores/xxx)
        
        Returns:
            list of document info from Gemini
        """
        try:
            docs = list(await asyncio.to_thread(
                self.gemini_client.file_search_stores.documents.list,
                parent=store_name
            ))
            
            return [
                {
                    "name": getattr(doc, "name", None),
                    "display_name": getattr(doc, "display_name", None),
                    "state": str(getattr(doc, "state", None)),
                    "size_bytes": int(getattr(doc, "size_bytes", 0) or 0),
                    "create_time": str(getattr(doc, "create_time", None)),
                }
                for doc in docs
            ]
        except Exception as e:
            logger.error(f"Failed to list Gemini documents: {e}", exc_info=True)
            raise GeminiException(f"Failed to list Gemini documents: {str(e)}")
    
    async def _sync_store_stats_by_id(self, store_id: str):
        """Sync store statistics from Gemini by store_id."""
        try:
            store_dict = await self.store_repo.find_by_id(store_id)
            if not store_dict:
                return
            
            store_name = store_dict["store_name"]
            await self._sync_store_stats(store_name, store_id)
        except Exception as e:
            logger.warning(f"Failed to sync store stats for store_id {store_id}: {e}")
    
    async def _sync_store_stats(self, store_name: str, store_id: Optional[str] = None):
        """Sync store statistics from Gemini after file operations."""
        try:
            if not store_id:
                store_dict = await self.store_repo.find_by_store_name(store_name)
                if not store_dict:
                    return
                store_id = str(store_dict["_id"])
            
            # Get from Gemini API
            gemini_store = await asyncio.to_thread(
                self.gemini_client.file_search_stores.get,
                name=store_name,
            )
            
            file_count = int(getattr(gemini_store, "active_documents_count", 0) or 0)
            total_size = int(getattr(gemini_store, "size_bytes", 0) or 0)
            
            await self.store_repo.update_statistics(store_id, file_count, total_size)
        except Exception as e:
            logger.warning(f"Failed to sync store stats for {store_name}: {e}")
    
    async def delete_all_files_in_store(self, store_id: str, gemini_only: bool = False) -> int:
        """
        Delete all files in a store.
        
        Args:
            store_id: Store ID (MongoDB ObjectId)
            gemini_only: If True, only delete from Gemini API (not MinIO/MongoDB)
            
        Returns:
            Number of files deleted
        """
        # Get store info
        store_dict = await self.store_repo.find_by_id(store_id)
        if not store_dict:
            raise NotFoundException("Store", store_id)
        
        store_name = store_dict["store_name"]
        
        # Get all files in store
        files = await self.file_repo.find_by_store(store_id, skip=0, limit=10000)
        deleted_count = 0
        
        for file_doc in files:
            try:
                gemini_document_name = file_doc.get("gemini_document_name")
                
                # Delete from Gemini
                if gemini_document_name:
                    try:
                        await asyncio.to_thread(
                            self.gemini_client.file_search_stores.documents.delete,
                            name=gemini_document_name,
                            config={"force": True}
                        )
                    except Exception as e:
                        logger.warning(f"Failed to delete {gemini_document_name} from Gemini: {e}")
                
                if not gemini_only:
                    # Delete from MinIO
                    if storage_path := file_doc.get("storage_path"):
                        try:
                            await minio_storage.delete_file(storage_path)
                        except Exception as e:
                            logger.warning(f"Failed to delete from MinIO: {e}")
                    
                    # Delete from MongoDB
                    await self.file_repo.delete_by_id(str(file_doc["_id"]))
                
                deleted_count += 1
                
            except Exception as e:
                logger.error(f"Failed to delete file {file_doc.get('_id')}: {e}")
        
        # Sync store stats
        await self._sync_store_stats(store_name, store_id)
        
        logger.info(f"Deleted {deleted_count} files from store {store_id} (gemini_only={gemini_only})")
        return deleted_count
    
    async def delete_all_files_in_store_gemini(self, store_id: str) -> int:
        """
        Delete all documents from Gemini File Search store only.
        Does NOT delete from MinIO or MongoDB.

        Args:
            store_id: Store ID (MongoDB ObjectId)

        Returns:
            Number of documents deleted from Gemini
        """
        return await self.delete_all_files_in_store(store_id, gemini_only=True)

    # ====================================
    # SYNC HELPERS
    # ====================================

    async def _list_all_minio_paths(self) -> set[str]:
        """Return set of all object_name paths currently in MinIO bucket."""
        files = await minio_storage.list_files(prefix="")
        return {f["object_name"] for f in files}

    async def _list_all_gemini_doc_names(self) -> set[str]:
        """Return set of all Gemini document names across every store."""
        gemini_names: set[str] = set()
        store_dicts = await self.store_repo.find_many({}, skip=0, limit=10000)
        for store in store_dicts:
            store_name = store["store_name"]
            try:
                docs = list(await asyncio.to_thread(
                    self.gemini_client.file_search_stores.documents.list,
                    parent=store_name,
                ))
                for doc in docs:
                    name = getattr(doc, "name", None)
                    if name:
                        gemini_names.add(name)
            except Exception as e:
                logger.warning(f"Could not list Gemini docs for store {store_name}: {e}")
        return gemini_names

    async def check_sync(self) -> dict:
        """
        Compare files across MongoDB, MinIO and Gemini.

        Returns dict with:
        - is_synced: bool
        - total_db / total_minio / total_gemini: int
        - synced_count: int  (files present in all 3)
        - issues: list of dicts describing each discrepancy
        """
        # Fetch from all 3 sources in parallel
        db_docs, minio_paths, gemini_names = await asyncio.gather(
            self.file_repo.find_many({}, skip=0, limit=100000),
            self._list_all_minio_paths(),
            self._list_all_gemini_doc_names(),
        )

        issues = []
        synced_count = 0

        # DB-based check
        db_storage_paths: set[str] = set()
        db_gemini_names: set[str] = set()
        for doc in db_docs:
            sp = doc.get("storage_path")
            gn = doc.get("gemini_document_name")
            file_id = str(doc.get("_id", ""))
            fname = doc.get("original_filename", "")

            in_minio = sp in minio_paths if sp else False
            in_gemini = gn in gemini_names if gn else False

            if sp:
                db_storage_paths.add(sp)
            if gn:
                db_gemini_names.add(gn)

            if in_minio and in_gemini:
                synced_count += 1
            elif not in_minio and not in_gemini:
                issues.append({
                    "file_id": file_id, "original_filename": fname,
                    "storage_path": sp, "gemini_document_name": gn,
                    "issue": "in_db_only",
                })
            elif not in_minio:
                issues.append({
                    "file_id": file_id, "original_filename": fname,
                    "storage_path": sp, "gemini_document_name": gn,
                    "issue": "missing_in_minio",
                })
            else:  # not in_gemini
                issues.append({
                    "file_id": file_id, "original_filename": fname,
                    "storage_path": sp, "gemini_document_name": gn,
                    "issue": "missing_in_gemini",
                })

        # MinIO objects with no DB record
        for sp in minio_paths - db_storage_paths:
            issues.append({
                "file_id": None, "original_filename": None,
                "storage_path": sp, "gemini_document_name": None,
                "issue": "in_minio_only",
            })

        # Gemini docs with no DB record
        for gn in gemini_names - db_gemini_names:
            issues.append({
                "file_id": None, "original_filename": None,
                "storage_path": None, "gemini_document_name": gn,
                "issue": "in_gemini_only",
            })

        return {
            "is_synced": len(issues) == 0,
            "total_db": len(db_docs),
            "total_minio": len(minio_paths),
            "total_gemini": len(gemini_names),
            "synced_count": synced_count,
            "issues": issues,
        }

    async def sync_files(self) -> dict:
        """
        Synchronise files across MongoDB, MinIO and Gemini.

        Strategy:
        - DB record exists + MinIO exists + Gemini missing
            → upload file from MinIO to Gemini
        - All other inconsistencies (orphan in any one/two sources)
            → delete from whichever sources have the file
        """
        check = await self.check_sync()
        if check["is_synced"]:
            return {
                "total_issues": 0,
                "uploaded_to_gemini": 0,
                "deleted": 0,
                "failed": 0,
                "results": [],
            }

        results = []
        uploaded = deleted = failed = 0

        for issue in check["issues"]:
            file_id = issue["file_id"]
            sp = issue["storage_path"]
            gn = issue["gemini_document_name"]
            fname = issue["original_filename"]
            issue_type = issue["issue"]
            result_base = {
                "file_id": file_id,
                "original_filename": fname,
                "storage_path": sp,
                "gemini_document_name": gn,
            }

            try:
                # ── Case 1: DB + MinIO, missing Gemini ─────────────────
                if issue_type == "missing_in_gemini" and file_id and sp:
                    doc = await self.file_repo.find_by_id(file_id)
                    if not doc:
                        raise ValueError("DB record disappeared during sync")

                    store_id = doc["store_id"]
                    store_dict = await self.store_repo.find_by_id(store_id)
                    if not store_dict:
                        raise ValueError(f"Store {store_id} not found")
                    store_name = store_dict["store_name"]

                    # Download from MinIO to temp file
                    import tempfile, os as _os
                    file_obj = await minio_storage.download_file(sp)
                    suffix = _os.path.splitext(doc.get("original_filename", ""))[1]
                    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                        tmp.write(file_obj.read())
                        tmp_path = tmp.name

                    try:
                        state = UploadState(
                            file_id=file_id, storage_path=sp,
                            completed_steps=[UploadStep.DB_CREATED, UploadStep.MINIO_UPLOADED],
                        )
                        await self.file_repo.update_by_id(file_id, {"status": FileStatus.PROCESSING.value})
                        await self._process_gemini_upload(
                            file_id, tmp_path,
                            doc.get("display_name", doc.get("original_filename", "")),
                            store_id, store_name,
                            doc.get("custom_metadata"), None, state,
                        )
                    finally:
                        self._cleanup_temp_file(tmp_path)

                    results.append({**result_base, "action": "upload_to_gemini", "success": True, "error": None})
                    uploaded += 1

                # ── Case 2: DB only (no MinIO, no Gemini) ──────────────
                elif issue_type == "in_db_only" and file_id:
                    await self.file_repo.delete_by_id(file_id)
                    results.append({**result_base, "action": "delete_db", "success": True, "error": None})
                    deleted += 1

                # ── Case 3: DB + Gemini, missing MinIO ─────────────────
                elif issue_type == "missing_in_minio" and file_id:
                    if gn:
                        try:
                            await asyncio.to_thread(
                                self.gemini_client.file_search_stores.documents.delete,
                                name=gn, config={"force": True},
                            )
                        except Exception as e:
                            logger.warning(f"Sync: could not delete Gemini doc {gn}: {e}")
                    await self.file_repo.delete_by_id(file_id)
                    results.append({**result_base, "action": "delete_db_and_gemini", "success": True, "error": None})
                    deleted += 1

                # ── Case 4: MinIO only ──────────────────────────────────
                elif issue_type == "in_minio_only" and sp:
                    await minio_storage.delete_file(sp)
                    results.append({**result_base, "action": "delete_minio", "success": True, "error": None})
                    deleted += 1

                # ── Case 5: Gemini only ─────────────────────────────────
                elif issue_type == "in_gemini_only" and gn:
                    await asyncio.to_thread(
                        self.gemini_client.file_search_stores.documents.delete,
                        name=gn, config={"force": True},
                    )
                    results.append({**result_base, "action": "delete_gemini", "success": True, "error": None})
                    deleted += 1

                else:
                    raise ValueError(f"Unhandled issue type: {issue_type}")

            except Exception as e:
                logger.error(f"Sync action failed for issue {issue_type} file_id={file_id}: {e}", exc_info=True)
                results.append({**result_base, "action": issue_type, "success": False, "error": str(e)})
                failed += 1

        return {
            "total_issues": len(check["issues"]),
            "uploaded_to_gemini": uploaded,
            "deleted": deleted,
            "failed": failed,
            "results": results,
        }


# Factory function for dependency injection
_file_service_instance: Optional["FileService"] = None


def get_file_service() -> FileService:
    """Get singleton FileService instance."""
    global _file_service_instance
    if _file_service_instance is None:
        _file_service_instance = FileService()
    return _file_service_instance
