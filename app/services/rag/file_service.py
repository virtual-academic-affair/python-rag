"""
File Service - Business logic for file management operations.
Handles file uploads, downloads, deletions, and GraphRAG indexing with Neo4j.
"""

import asyncio
import logging
import mimetypes
import os
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
    ConflictException,
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
    UploadStep,
    UploadState,
)
from app.services.rag.metadata_service import get_metadata_service
from app.services.rag.ingestion.llama_parser_service import llama_parser_service
from app.services.rag.ingestion.chunking_service import chunking_service
from app.services.rag.ingestion.embedding_service import embedding_service
from app.services.rag.graph.graph_ingestion_service import graph_ingestion_service

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
                
                # 3. Parse -> Chunk -> Embed -> Index Neo4j (Sprint 1)
                if not state.has_step(UploadStep.GEMINI_UPLOADED):
                    logger.info(f"[{state.file_id}] Processing GraphRAG indexing")
                    chunk_count = await self._index_to_graph(
                        file_id=state.file_id,
                        file_path=file_path,
                        store_id=store_id,
                        display_name=display_name,
                        custom_metadata=state.custom_metadata,
                    )
                    state.mark_step(UploadStep.GEMINI_UPLOADED)

                    await self.file_repo.update_by_id(
                        state.file_id,
                        {
                            "status": FileStatus.ACTIVE.value,
                            "chunk_count": chunk_count,
                        },
                    )

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

    async def _index_to_graph(
        self,
        file_id: str,
        file_path: str,
        store_id: str,
        display_name: str,
        custom_metadata: Optional[dict],
    ) -> int:
        markdown_text = await asyncio.to_thread(llama_parser_service.parse_to_markdown, file_path)
        if not markdown_text:
            markdown_text = ""

        chunks = chunking_service.chunk_markdown(markdown_text, file_id)
        if not chunks:
            return 0

        vectors = await embedding_service.embed_texts([c.text for c in chunks])
        return await asyncio.to_thread(
            graph_ingestion_service.upsert_document_and_chunks,
            doc_id=file_id,
            store_id=store_id,
            title=display_name,
            chunks=chunks,
            embeddings=vectors,
            custom_metadata=custom_metadata,
        )

    async def _rollback_upload(self, state: UploadState, error_msg: str) -> None:
        """Rollback file and metadata state on failure."""
        logger.warning(f"Rolling back upload (file_id={state.file_id}): {error_msg}")

        if state.has_step(UploadStep.METADATA_SYNCED) and state.custom_metadata:
            try:
                await self.metadata_svc.sync_metadata_counters(state.custom_metadata, delta=-1)
            except Exception as e:
                logger.warning(f"Rollback metadata counters failed: {e}")

        if state.has_step(UploadStep.R2_UPLOADED) and state.storage_path:
            try:
                await r2_storage.delete_file(state.storage_path)
            except Exception as e:
                logger.warning(f"Rollback R2 delete failed: {e}")

        if state.has_step(UploadStep.DB_CREATED) and state.file_id:
            try:
                await self.file_repo.delete_by_id(state.file_id)
            except Exception as e:
                logger.warning(f"Rollback DB delete failed: {e}")

    
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
        
        store_id = file_doc.get("store_id")

        # Delete from Cloudflare R2
        if storage_path := file_doc.get("storage_path"):
            try:
                await r2_storage.delete_file(storage_path)
            except Exception as e:
                logger.warning(f"Failed to delete from Cloudflare R2: {e}")
        
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

        # Get all files in store
        files = await self.file_repo.find_by_store(store_id, skip=0, limit=10000)
        deleted_count = 0
        
        for file_doc in files:
            try:
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
        """Deprecated in GraphRAG mode (kept for backward compatibility)."""
        return set()

    async def check_sync(self) -> dict:
        """Compare MongoDB records with R2 objects (GraphRAG mode)."""
        db_docs, r2_paths = await asyncio.gather(
            self.file_repo.find_many({}, skip=0, limit=100000),
            self._list_all_r2_paths(),
        )

        issues = []
        synced_count = 0

        for doc in db_docs:
            sp = doc.get("storage_path")
            in_r2 = sp in r2_paths if sp else False
            if in_r2:
                synced_count += 1
            else:
                issues.append(
                    {
                        "file_id": str(doc.get("_id", "")),
                        "original_filename": doc.get("original_filename", ""),
                        "storage_path": sp,
                        "gemini_document_name": doc.get("gemini_document_name"),
                        "issue": "missing_in_r2",
                    }
                )

        db_storage_paths = {doc.get("storage_path") for doc in db_docs if doc.get("storage_path")}
        for path in r2_paths:
            if path not in db_storage_paths:
                issues.append(
                    {
                        "file_id": None,
                        "original_filename": path.split("/")[-1],
                        "storage_path": path,
                        "gemini_document_name": None,
                        "issue": "in_r2_only",
                    }
                )

        return {
            "is_synced": len(issues) == 0,
            "total_db": len(db_docs),
            "total_r2": len(r2_paths),
            "total_gemini": 0,
            "synced_count": synced_count,
            "issues": issues,
        }


    async def sync_files(self) -> dict:
        """Synchronise MongoDB and Cloudflare R2 consistency in GraphRAG mode."""
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
        deleted = failed = 0

        for issue in check["issues"]:
            file_id = issue["file_id"]
            sp = issue["storage_path"]
            fname = issue["original_filename"]
            issue_type = issue["issue"]
            result_base = {
                "file_id": file_id,
                "original_filename": fname,
                "storage_path": sp,
                "gemini_document_name": issue.get("gemini_document_name"),
            }

            try:
                if issue_type == "missing_in_r2" and file_id:
                    await self.file_repo.delete_by_id(file_id)
                    results.append({**result_base, "action": "delete_db", "success": True, "error": None})
                    deleted += 1
                elif issue_type == "in_r2_only" and sp:
                    await r2_storage.delete_file(sp)
                    results.append({**result_base, "action": "delete_r2", "success": True, "error": None})
                    deleted += 1
                else:
                    results.append({**result_base, "action": issue_type, "success": True, "error": None})
            except Exception as e:
                logger.error(f"Sync action failed for issue {issue_type} file_id={file_id}: {e}", exc_info=True)
                results.append({**result_base, "action": issue_type, "success": False, "error": str(e)})
                failed += 1

        return {
            "total_issues": len(check["issues"]),
            "uploaded_to_gemini": 0,
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
