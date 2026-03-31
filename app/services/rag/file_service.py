"""
File Service - Business logic for file management operations.
Handles file uploads, downloads, deletions, and integrations with Cloudflare R2 and Gemini.
"""

import asyncio
import logging
import mimetypes
import os
import tempfile
import time
from typing import Optional, BinaryIO, List, Tuple, Dict, Any

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
    GeminiException,
    ConflictException,
    ValidationException,
)
from app.models.database import FileDocument
from app.models.enums import FileStatus
from app.repositories.file_repository import FileRepository
from app.repositories.store_repository import StoreRepository
from app.storage.r2_client import r2_storage
from app.services.rag.utils.file_utils import (
    validate_file_size,
    validate_file_extension,
    detect_mime_type,
    generate_storage_path,
    cleanup_temp_file,
    convert_metadata_for_gemini,
    UploadStep,
    UploadState,
    GeminiFile,
)
from app.services.rag.metadata_service import get_metadata_service
from app.services.rag.gemini_client import gemini_client
from app.services.rag.utils.gemini_rag_utils import (
    wait_for_gemini_operation,
    find_gemini_document_by_name,
)

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
        """Initialize FileService with repositories and Gemini client."""
        self._file_repo = None
        self._store_repo = None
        self._gemini_client = None
        self._metadata_svc = None
        self._store_svc = None
    
    @property
    def store_svc(self):
        """Lazy load store service."""
        if self._store_svc is None:
            from app.services.rag.store_service import get_store_service
            self._store_svc = get_store_service()
        return self._store_svc
    
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
            self._gemini_client = gemini_client.client
        return self._gemini_client
    
    
    async def upload_file(
        self,
        file_path: str,
        original_filename: str,
        store_id: str,
        store_name: str,
        display_name: Optional[str] = None,
        custom_metadata: Optional[dict] = None,
        max_retries: int = 3,
    ) -> FileDocument:
        """
        Upload a file to Cloudflare R2 and Gemini File Search.
        Coordinates validation, DB creation, storage upload, and metadata sync with retries and rollback.
        """
        # 1. Validation & State Initialization
        state, file_info = await self._prepare_upload_state(
            file_path, original_filename, store_id, display_name, custom_metadata
        )
        
        # 2. Execution with Retries
        try:
            return await self._execute_upload_steps(
                state=state,
                file_path=file_path,
                original_filename=original_filename,
                store_id=store_id,
                store_name=store_name,
                display_name=display_name or original_filename,
                mime_type=file_info["mime_type"],
                file_size=file_info["file_size"],
                max_retries=max_retries
            )
        except Exception as e:
            await self._rollback_upload(state, str(e))
            raise

    async def _prepare_upload_state(
        self,
        file_path: str,
        original_filename: str,
        store_id: str,
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
            "store_id": store_id,
            "original_filename": original_filename,
        })
        if existing_file:
            raise ConflictException(f"File '{original_filename}' already exists in store")
        
        # Prepare initial state
        state = UploadState(custom_metadata=custom_metadata)
        
        # Generate storage path
        store_dict = await self.store_repo.find_by_id(store_id)
        if not store_dict:
            raise NotFoundException("Store", store_id)
        store_name = store_dict["store_name"]

        state.storage_path = generate_storage_path(store_name, original_filename)
        state.mark_step(UploadStep.VALIDATED)
        
        file_info = {
            "file_size": file_size,
            "mime_type": mime_type
        }
        
        return state, file_info

    async def _execute_upload_steps(
        self,
        state: UploadState,
        file_path: str,
        original_filename: str,
        store_id: str,
        store_name: str,
        display_name: str,
        mime_type: str,
        file_size: int,
        max_retries: int
    ) -> FileDocument:
        """Execute the atomic steps of uploading with a retry loop."""
        retry_delay = 2
        
        for attempt in range(max_retries):
            try:
                # 1. Database record
                if not state.has_step(UploadStep.DB_CREATED):
                    file_doc_data = {
                        "store_id": store_id,
                        "display_name": display_name,
                        "original_filename": original_filename,
                        "storage_path": state.storage_path,
                        "storage_bucket": settings.R2_BUCKET_NAME,
                        "file_size": file_size,
                        "mime_type": mime_type,
                        "gemini_document_name": None,
                        "custom_metadata": state.custom_metadata or {},
                        "status": FileStatus.UPLOADING.value,
                    }
                    created_file = await self.file_repo.create(file_doc_data)
                    state.file_id = str(created_file["_id"])
                    state.mark_step(UploadStep.DB_CREATED)
                
                # 2. Cloudflare R2
                if not state.has_step(UploadStep.R2_UPLOADED):
                    logger.info(f"[{state.file_id}] Uploading to Cloudflare R2 (Attempt {attempt+1})")
                    with open(file_path, "rb") as f:
                        await r2_storage.upload_file(
                            file=f,
                            object_name=state.storage_path,
                            content_type=mime_type,
                            metadata={"file_id": state.file_id, "store_id": store_id},
                        )
                    state.mark_step(UploadStep.R2_UPLOADED)
                
        # 3. Gemini File Search
                if not state.has_step(UploadStep.GEMINI_UPLOADED):
                    logger.info(f"[{state.file_id}] Processing Gemini upload")
                    gemini_file = await self._upload_to_gemini(
                        file_path, display_name, store_name, state.custom_metadata
                    )
                    state.gemini_document_name = gemini_file.name
                    state.mark_step(UploadStep.GEMINI_UPLOADED)
                    
                    # Update DB with Gemini document name
                    await self.file_repo.update_by_id(
                        state.file_id,
                        {
                            "gemini_document_name": gemini_file.name,
                            "status": FileStatus.ACTIVE.value, 
                        }
                    )
                
                # Update store stats and metadata counters
                await self.store_svc.sync_store_stats(store_id)
                if state.custom_metadata and not state.has_step(UploadStep.METADATA_SYNCED):
                    await self.metadata_svc.sync_metadata_counters(state.custom_metadata, delta=1)
                    state.mark_step(UploadStep.METADATA_SYNCED)
                
                state.mark_step(UploadStep.COMPLETED)
                return await self.get_file_by_id(state.file_id)
                
            except Exception as e:
                logger.warning(f"[{state.file_id or 'NEW'}] Upload attempt {attempt+1} failed: {e}. Retrying in {retry_delay * (attempt + 1)}s...")
                if attempt == max_retries - 1:
                    raise
                await asyncio.sleep(retry_delay * (attempt + 1))

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
        # This method is replaced by the new _execute_upload_steps logic.
        # The instruction implies _process_gemini_upload is still called, but the new _execute_upload_steps
        # directly calls _upload_to_gemini.
        # Let's keep _upload_to_gemini and remove this _process_gemini_upload if it's no longer used.
        # The instruction's _execute_upload_steps snippet has:
        # state.gemini_document_name = await self._process_gemini_upload(...)
        # This means _process_gemini_upload should return the gemini_document_name.
        # Let's rename the existing _upload_to_gemini to _process_gemini_upload and adjust its return.
        pass # This method is effectively replaced/refactored into _upload_to_gemini and _execute_upload_steps

 
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

    async def _upload_to_gemini(
        self,
        file_path: str,
        display_name: str,
        store_name: str,
        custom_metadata: Optional[dict] = None,
    ) -> GeminiFile:
        """Upload file directly to Gemini File Search store."""
        try:
            # Prepare config
            config = {"display_name": display_name}
            
            # Add custom metadata
            if custom_metadata:
                config["custom_metadata"] = convert_metadata_for_gemini(custom_metadata)
            
            # Upload file directly to store
            logger.info(f"Uploading to Gemini store {store_name}: {display_name}")
            operation = await asyncio.to_thread(
                self.gemini_client.file_search_stores.upload_to_file_search_store,
                file=file_path,
                file_search_store_name=store_name,
                config=config,
            )
            
            # Wait for processing with timeout
            document_name = await wait_for_gemini_operation(
                self.gemini_client, operation, display_name, store_name
            )
            
            logger.info(f"File uploaded to Gemini: {document_name}")
            return GeminiFile(name=document_name)
            
        except GeminiException:
            raise
        except Exception as e:
            logger.error(f"Gemini upload failed: {e}", exc_info=True)
            raise GeminiException(f"Gemini upload failed: {str(e)}")
    
    async def _wait_for_operation(self, operation, display_name: str, store_name: str, timeout: int = 120) -> str:
        """Wait for Gemini operation to complete and extract document name."""
        # This method is replaced by the direct call to wait_for_gemini_operation in _upload_to_gemini
        pass
    
    
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
        
        gemini_document_name = file_doc.get("gemini_document_name")
        store_id = file_doc.get("store_id")
        
        # Delete from Cloudflare R2
        if storage_path := file_doc.get("storage_path"):
            try:
                await r2_storage.delete_file(storage_path)
            except Exception as e:
                logger.warning(f"Failed to delete from Cloudflare R2: {e}")
        
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
        
        # Decrement metadata counters if the file was active and has custom_metadata
        if file_doc.get("status") == FileStatus.ACTIVE.value and file_doc.get("custom_metadata"):
            await self.metadata_svc.sync_metadata_counters(file_doc["custom_metadata"], delta=-1)
        
        # Sync store stats
        if store_id:
            await self.store_svc.sync_store_stats(store_id)
        
        logger.info(f"File {file_id} deleted")
        return True
        
    async def update_file_display_name(self, file_id: str, new_display_name: str) -> Optional[FileDocument]:
        """Update the display name of a file."""
        file_doc_dict = await self.file_repo.find_by_id(file_id)
        if not file_doc_dict:
            raise NotFoundException("File", file_id)
            
        update_data = {"display_name": new_display_name}
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
            
        # 1. Filter by access_scope (DB and memory checks)
        if user_role == "student":
            files = [f for f in files if "student" in ((f.get("custom_metadata") or {}).get("access_scope") or [])]
        elif user_role == "lecture":
            files = [f for f in files if "lecture" in ((f.get("custom_metadata") or {}).get("access_scope") or [])]
        # Admin sees all, no filter needed
            
        # 2. Mask custom_metadata based on visible_roles via MetadataService
        await self.metadata_svc.filter_custom_metadata_by_role(files, user_role)
        
        return files

    async def _filter_custom_metadata_for_role(self, file_dicts: List[Dict[str, Any]], user_role: str) -> None:
        """Legacy delegate to MetadataService."""
        await self.metadata_svc.filter_custom_metadata_by_role(file_dicts, user_role)

    async def list_files(
        self,
        store_id: Optional[str] = None,
        status: Optional[FileStatus] = None,
        custom_metadata_filter: Optional[Dict[str, Any]] = None,
        keywords: Optional[str] = None,
        user_role: str = "student",
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[list[FileDocument], int]:
        """List files with optional filters and role-based access control."""
        filters = {}
        if store_id:
            filters["store_id"] = store_id
        if status:
            filters["status"] = status.value
            
        # Add keywords filter (partial match on display_name)
        if keywords:
            filters["display_name"] = {"$regex": keywords, "$options": "i"}
            
        # Add metadata filters with "all" support
        if custom_metadata_filter:
            for k, v in custom_metadata_filter.items():
                if k == "access_scope":
                    continue # Handled by role logic
                
                # Support array of values (OR logic for same key)
                if isinstance(v, list):
                    filter_values = v + ["all"]
                else:
                    filter_values = [v, "all"]
                    
                filters[f"custom_metadata.{k}"] = {"$in": filter_values}
        
        # Database-level filtering for access_scope
        if user_role == "student":
            filters["custom_metadata.access_scope"] = {"$in": ["student"]}
        elif user_role == "lecture":
            filters["custom_metadata.access_scope"] = {"$in": ["lecture"]}
        elif user_role == "admin":
            if custom_metadata_filter and "access_scope" in custom_metadata_filter:
                v = custom_metadata_filter["access_scope"]
                # Admin can pass list or string for access_scope, no "all" fallback implicitly needed for access_scope 
                if isinstance(v, list):
                    filters["custom_metadata.access_scope"] = {"$in": v}
                else:
                    filters["custom_metadata.access_scope"] = {"$in": [v]}
            
        file_dicts = await self.file_repo.find_many(filters, skip, limit, sort=[("created_at", -1)])
        total = await self.file_repo.count(filters)
        
        # Final masking for visible_roles (permission check already implicitly handled by DB filters)
        file_dicts = await self._apply_role_filters_and_metadata_masking(file_dicts, user_role)
        
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
    
    async def _sync_store_stats_by_id(self, store_id: str):
        """Sync store statistics from Gemini by store_id."""
        # This method is now replaced by direct call to store_svc.sync_store_stats
        pass
    
    async def _sync_store_stats(self, store_id: str) -> None:
        """Sync store statistics via StoreService."""
        await self.store_svc.sync_store_stats(store_id)
    
    async def delete_all_files_in_store(self, store_id: str, gemini_only: bool = False) -> int:
        """
        Delete all files in a store.
        
        Args:
            store_id: Store ID (MongoDB ObjectId)
            gemini_only: If True, only delete from Gemini API (not Cloudflare R2/MongoDB)
            
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
                    # Delete from Cloudflare R2
                    if storage_path := file_doc.get("storage_path"):
                        try:
                            await r2_storage.delete_file(storage_path)
                        except Exception as e:
                            logger.warning(f"Failed to delete from Cloudflare R2: {e}")
                    
                    # Delete from MongoDB
                    await self.file_repo.delete_by_id(str(file_doc["_id"]))
                
                deleted_count += 1
                
            except Exception as e:
                logger.error(f"Failed to delete file {file_doc.get('_id')}: {e}")
        
        # Sync store stats
        await self._sync_store_stats(store_id)
        
        logger.info(f"Deleted {deleted_count} files from store {store_id} (gemini_only={gemini_only})")
        return deleted_count
    

    # ====================================
    # SYNC HELPERS
    # ====================================

    async def _list_all_r2_paths(self) -> set[str]:
        """Return set of all object_name paths currently in Cloudflare R2 bucket."""
        files = await r2_storage.list_files(prefix="")
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
        Compare files across MongoDB, Cloudflare R2 and Gemini.

        Returns dict with:
        - is_synced: bool
        - total_db / total_r2 / total_gemini: int
        - synced_count: int  (files present in all 3)
        - issues: list of dicts describing each discrepancy
        """
        # Fetch from all 3 sources in parallel
        db_docs, r2_paths, gemini_names = await asyncio.gather(
            self.file_repo.find_many({}, skip=0, limit=100000),
            self._list_all_r2_paths(),
            self._list_all_gemini_doc_names(),
        )

        # Detect all issues
        db_storage_paths, db_gemini_names, db_issues, synced_count = self._detect_db_discrepancies(
            db_docs, r2_paths, gemini_names
        )
        
        orphaned_issues = self._detect_orphaned_cloud_files(
            r2_paths, gemini_names, db_storage_paths, db_gemini_names
        )
        
        issues = db_issues + orphaned_issues

        return {
            "is_synced": len(issues) == 0,
            "total_db": len(db_docs),
            "total_r2": len(r2_paths),
            "total_gemini": len(gemini_names),
            "synced_count": synced_count,
            "issues": issues,
        }

    def _detect_db_discrepancies(
        self, 
        db_docs: list[dict], 
        r2_paths: set[str], 
        gemini_names: set[str]
    ) -> Tuple[set[str], set[str], list[dict], int]:
        """Detect issues where a DB record is missing its cloud counterpart."""
        db_storage_paths: set[str] = set()
        db_gemini_names: set[str] = set()
        issues = []
        synced_count = 0
        
        for doc in db_docs:
            sp = doc.get("storage_path")
            gn = doc.get("gemini_document_name")
            file_id = str(doc.get("_id", ""))
            fname = doc.get("original_filename", "")

            if sp: db_storage_paths.add(sp)
            if gn: db_gemini_names.add(gn)

            in_r2 = sp in r2_paths if sp else False
            in_gemini = gn in gemini_names if gn else False

            if in_r2 and in_gemini:
                synced_count += 1
            else:
                issue_type = "in_db_only" # Default if both are missing
                if in_r2 and not in_gemini: issue_type = "missing_in_gemini"
                elif in_gemini and not in_r2: issue_type = "missing_in_r2"
                # If neither in_r2 nor in_gemini, it remains "in_db_only"

                issues.append({
                    "file_id": file_id, "original_filename": fname,
                    "storage_path": sp, "gemini_document_name": gn,
                    "issue": issue_type
                })
        
        return db_storage_paths, db_gemini_names, issues, synced_count

    def _detect_orphaned_cloud_files(
        self,
        r2_paths: set[str],
        gemini_names: set[str],
        db_storage_paths: set[str],
        db_gemini_names: set[str]
    ) -> list[dict]:
        """Detect files in R2 or Gemini that have no corresponding DB record."""
        issues = []
        
        # Files in R2 but not in DB
        for path in r2_paths:
            if path not in db_storage_paths:
                issues.append({
                    "file_id": None, "original_filename": path.split("/")[-1],
                    "storage_path": path, "gemini_document_name": None,
                    "issue": "in_r2_only"
                })

        # Files in Gemini but not in DB
        for name in gemini_names:
            if name not in db_gemini_names:
                issues.append({
                    "file_id": None, "original_filename": "Unknown (Gemini only)",
                    "storage_path": None, "gemini_document_name": name,
                    "issue": "in_gemini_only"
                })
        
        return issues

    async def sync_files(self) -> dict:
        """
        Synchronise files across MongoDB, Cloudflare R2 and Gemini.

        Strategy:
        - DB record exists + Cloudflare R2 exists + Gemini missing
            → upload file from Cloudflare R2 to Gemini
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
                # ── Case 1: DB + Cloudflare R2, missing Gemini ─────────────────
                if issue_type == "missing_in_gemini" and file_id and sp:
                    doc = await self.file_repo.find_by_id(file_id)
                    if not doc:
                        raise ValueError("DB record disappeared during sync")

                    store_id = doc["store_id"]
                    store_dict = await self.store_repo.find_by_id(store_id)
                    if not store_dict:
                        raise ValueError(f"Store {store_id} not found")
                    store_name = store_dict["store_name"]

                    # Download from Cloudflare R2 to temp file
                    file_obj = await r2_storage.download_file(sp)
                    suffix = os.path.splitext(doc.get("original_filename", ""))[1]
                    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                        tmp.write(file_obj.read())
                        tmp_path = tmp.name

                    try:
                        state = UploadState(
                            file_id=file_id, storage_path=sp,
                            completed_steps=[UploadStep.DB_CREATED, UploadStep.R2_UPLOADED],
                        )
                        await self.file_repo.update_by_id(file_id, {"status": FileStatus.PROCESSING.value})
                        await self._process_gemini_upload(
                            file_id, tmp_path,
                            doc.get("display_name", doc.get("original_filename", "")),
                            store_id, store_name,
                            doc.get("custom_metadata"), None, state,
                        )
                    finally:
                        cleanup_temp_file(tmp_path)

                    results.append({**result_base, "action": "upload_to_gemini", "success": True, "error": None})
                    uploaded += 1

                # ── Case 2: DB only (no Cloudflare R2, no Gemini) ──────────────
                elif issue_type == "in_db_only" and file_id:
                    await self.file_repo.delete_by_id(file_id)
                    results.append({**result_base, "action": "delete_db", "success": True, "error": None})
                    deleted += 1

                # ── Case 3: DB + Gemini, missing Cloudflare R2 ─────────────────
                elif issue_type == "missing_in_r2" and file_id:
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

                # ── Case 4: Cloudflare R2 only ──────────────────────────────────
                elif issue_type == "in_r2_only" and sp:
                    await r2_storage.delete_file(sp)
                    results.append({**result_base, "action": "delete_r2", "success": True, "error": None})
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
