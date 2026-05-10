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
from typing import Optional, BinaryIO, List, Tuple, Dict, Any, Callable, Awaitable, Literal

from app.integrations.llamaparse.client import get_llamaparse_client
from app.core.text_utils import remove_accents


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
from app.integrations.qdrant.indexer import get_qdrant_indexer
from app.modules.files.upload_state import (
    UploadStep,
    UploadState,
)
from app.modules.files.toc_tree.repository import FileTocTreeRepository
from app.integrations.pageindex.client import get_page_index_client
from app.modules.metadata.utils.filter_builder import get_filter_builder
from app.modules.files.service_upload import FileUploadMixin

logger = logging.getLogger(__name__)


def _to_file_model(doc: dict) -> Optional[FileDocument]:
    """Convert dict to FileDocument."""
    if not doc:
        return None
    return FileDocument(**doc)

class FileService(FileUploadMixin):
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

    async def download_file(
        self, 
        file_id: str, 
        user_role: Optional[str] = None,
        file_format: Literal["original", "markdown"] = "original"
    ) -> tuple[BinaryIO, str, str]:
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

        if file_format == "markdown":
            if not file_doc.markdown_storage_path:
                raise NotFoundException("Markdown artifact for file", file_id)
            storage_path = file_doc.markdown_storage_path
            # Use display_name for markdown filename if available
            download_name = f"{Path(file_doc.display_name or file_doc.original_filename).stem}.md"
            mime_type = "text/markdown"
        else:
            storage_path = file_doc.storage_path
            download_name = file_doc.original_filename
            mime_type = file_doc.mime_type

        try:
            file_obj = await r2_storage.download_file(storage_path)
            return file_obj, download_name, mime_type
        except Exception as e:
            logger.error(f"Download failed for {file_id} ({file_format}): {e}", exc_info=True)
            raise StorageException(f"File download failed: {str(e)}")


    async def delete_file(self, file_id: str) -> bool:
        """
        Delete file from storage, vector DB, and metadata counters.
        Atomic hard delete from MongoDB.
        """
        # Fetch file info first to get storage path and metadata
        file_doc = await self.file_repo.find_by_id(file_id)
        if not file_doc:
            raise NotFoundException("File", file_id)

        # Delete from Cloudflare R2
        if storage_path := file_doc.get("storage_path"):
            try:
                await r2_storage.delete_file(storage_path)
            except Exception as e:
                logger.warning(f"Failed to delete from Cloudflare R2: {e}")

        if markdown_storage_path := file_doc.get("markdown_storage_path"):
            try:
                await r2_storage.delete_file(markdown_storage_path)
            except Exception as e:
                logger.warning(f"Failed to delete markdown artifact from Cloudflare R2: {e}")

        # Xóa Qdrant
        indexer = get_qdrant_indexer()
        await indexer.delete_by_file_id(file_id)

        # Xóa file_toc_trees
        toc_repo = FileTocTreeRepository()
        await toc_repo.delete_by_file_id(file_id)

        # Xóa cache PageIndex (Redis + local .md file)
        page_index_client = get_page_index_client()
        await page_index_client.evict_doc(file_id)

        # Atomic hard delete from MongoDB
        deleted_doc = await self.file_repo.find_one_and_delete({"_id": self.file_repo._to_object_id(file_id)})

        if deleted_doc:
            logger.info(f"File {file_id} deleted from MongoDB")
            return True
            
        return False

    async def update_file(
        self,
        file_id: str,
        display_name: Optional[str] = None,
        custom_metadata: Optional[Dict[str, Any]] = None
    ) -> Optional[FileDocument]:
        """
        Update file details (display name and/or metadata).
        Syncs metadata to Qdrant if provided.
        """
        file_doc_dict = await self.file_repo.find_by_id(file_id)
        if not file_doc_dict:
            raise NotFoundException("File", file_id)

        update_data = {}
        if display_name is not None:
            update_data["display_name"] = display_name
            update_data["display_name_unaccented"] = remove_accents(display_name)

        if custom_metadata is not None:
            # Validate metadata before updating using the stateless validator
            validator = get_metadata_service()
            is_valid, errors, meta_model = validator.validate_and_parse_file_metadata(custom_metadata)
            if not is_valid:
                raise ValidationException(f"Invalid custom metadata: {', '.join(errors)}")
            update_data["custom_metadata"] = meta_model.model_dump(mode="json") if meta_model else None

        if not update_data:
            return _to_file_model(file_doc_dict)

        update_success = await self.file_repo.update_by_id(file_id, update_data)

        if update_success:
            # Sync to Qdrant if metadata changed
            if custom_metadata is not None:
                try:
                    indexer = get_qdrant_indexer()
                    await indexer.update_payload_by_file_id(file_id, update_data["custom_metadata"] or {})
                    logger.info(f"[FileService] Synced metadata to Qdrant for file {file_id}")
                except Exception as e:
                    logger.warning(f"[FileService] Failed to sync metadata to Qdrant for file {file_id}: {e}")

            # Merge for response
            file_doc_dict.update(update_data)
            return _to_file_model(file_doc_dict)
            
        return None

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
            unaccented_kw = remove_accents(keywords)
            filters["$or"] = [
                {"display_name_unaccented": {"$regex": unaccented_kw, "$options": "i"}},
                {"original_filename_unaccented": {"$regex": unaccented_kw, "$options": "i"}}
            ]

        # Add metadata filters
        builder = get_filter_builder()
        mongo_filter = await builder.build_mongo_filter(
            metadata_filter=custom_metadata_filter or {},
            mongo_prefix="custom_metadata",
            user_role=user_role,
            skip_validation=True
        )
        
        # Safe merge: prevent $or key collision when combining keyword filter with mongo_filter
        if mongo_filter:
            keyword_or = filters.pop("$or", None)
            filters.update(mongo_filter)
            if keyword_or:
                # Wrap keyword $or inside $and so it doesn't get overwritten
                filters["$and"] = filters.get("$and", []) + [{"$or": keyword_or}]

        file_dicts = await self.file_repo.find_many(filters, skip, limit, sort=[("created_at", -1)])
        total = await self.file_repo.count(filters)

        files = [_to_file_model(f) for f in file_dicts]
        return files, total

    async def get_file_by_id(self, file_id: str, user_role: Optional[str] = None) -> Optional[FileDocument]:
        """Get a single file by ID."""
        file_dict = await self.file_repo.find_by_id(file_id)
        if not file_dict:
            return None
        return _to_file_model(file_dict)

    async def get_file_data(self, file_id: str, user_role: str = "student") -> tuple[Any, FileDocument]:
        """Get file bytes and document for download."""
        file_doc_dict = await self.file_repo.find_by_id(file_id)
        if not file_doc_dict:
            raise NotFoundException("File", file_id)

        file_doc = _to_file_model(file_doc_dict)
        
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
