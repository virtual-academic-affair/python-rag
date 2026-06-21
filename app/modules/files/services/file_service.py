import logging
from pathlib import Path
from typing import Optional, BinaryIO, Dict, Any, Literal

from app.core.exceptions import (
    AppException,
    ExternalServiceException,
    NotFoundException,
    StorageException,
    ValidationException,
)
from app.modules.files.models.file import FileDocument, FileStatus
from app.modules.files.repositories.file_repository import FileRepository
from app.integrations.storage.client import r2_storage
from app.modules.metadata.services.metadata_service import get_metadata_service
from app.utils.text_utils import remove_accents
from app.integrations.qdrant.indexer import get_qdrant_indexer
from app.modules.files.toc_tree.repositories.toc_tree_repository import FileTocTreeRepository
from app.modules.metadata.utils.filter_builder import get_filter_builder
from app.modules.files.services.file_upload_service import FileUploadMixin

logger = logging.getLogger(__name__)

class FileService(FileUploadMixin):
    """
    Service for file management operations.
    Coordinates between Cloudflare R2 storage, MongoDB (Beanie), and Gemini/Qdrant.
    """

    def __init__(self):
        self._file_repo = None
        self._metadata_svc = None

    @property
    def metadata_svc(self):
        if self._metadata_svc is None:
            self._metadata_svc = get_metadata_service()
        return self._metadata_svc

    @property
    def file_repo(self) -> FileRepository:
        if self._file_repo is None:
            self._file_repo = FileRepository()
        return self._file_repo

    async def download_file(
        self, 
        file_id: str, 
        file_format: Literal["original", "markdown"] = "original"
    ) -> tuple[BinaryIO, str, str]:
        """Download a file from Cloudflare R2."""
        file_doc = await self.get_file_by_id(file_id)
        if not file_doc:
            raise NotFoundException("File", file_id)

        if file_format == "markdown":
            if not file_doc.markdown_storage_path:
                raise NotFoundException("Markdown artifact for file", file_id)
            storage_path = file_doc.markdown_storage_path
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
        """Delete file from indexes, storage, and database (Beanie hard delete)."""
        file_doc = await self.file_repo.find_by_id(file_id)
        if not file_doc:
            raise NotFoundException("File", file_id)

        indexer = get_qdrant_indexer()
        await indexer.delete_by_file_id(file_id)

        toc_repo = FileTocTreeRepository()
        await toc_repo.delete_by_file_id(file_id)

        from app.integrations.pageindex.client import get_page_index_client
        page_index_client = get_page_index_client()
        await page_index_client.evict_doc(file_id)

        if file_doc.storage_path:
            try:
                await r2_storage.delete_file(file_doc.storage_path)
            except Exception as e:
                logger.warning(f"Failed to delete from Cloudflare R2: {e}")

        if file_doc.markdown_storage_path:
            try:
                await r2_storage.delete_file(file_doc.markdown_storage_path)
            except Exception as e:
                logger.warning(f"Failed to delete markdown artifact from Cloudflare R2: {e}")

        await self.file_repo.delete(file_doc)
        logger.info(f"File {file_id} deleted from MongoDB")
        return True

    async def update_file(
        self,
        file_id: str,
        display_name: Optional[str] = None,
        custom_metadata: Optional[Dict[str, Any]] = None
    ) -> Optional[FileDocument]:
        """Update file details (display name and/or metadata) and syncs to Qdrant."""
        file_doc = await self.file_repo.find_by_id(file_id)
        if not file_doc:
            raise NotFoundException("File", file_id)

        old_display_name = file_doc.display_name
        old_metadata = file_doc.custom_metadata
        new_display_name = file_doc.display_name
        new_metadata = file_doc.custom_metadata

        if display_name is not None:
            new_display_name = display_name

        if custom_metadata is not None:
            validator = get_metadata_service()
            is_valid, errors, meta_model = validator.merge_file_metadata_update(
                existing=old_metadata,
                incoming_update=custom_metadata,
            )
            if not is_valid:
                raise ValidationException(f"Invalid merged metadata: {', '.join(errors)}")

            new_metadata = meta_model

        display_name_changed = new_display_name != old_display_name
        metadata_changed = new_metadata != old_metadata

        if display_name_changed or metadata_changed:
            indexer = get_qdrant_indexer()
            new_metadata_payload = new_metadata.model_dump(mode="json") if metadata_changed and new_metadata else None
            new_qdrant_name = new_display_name if display_name_changed else None
            try:
                await indexer.update_payload_by_file_id(
                    file_id=file_id,
                    new_metadata=new_metadata_payload,
                    file_name=new_qdrant_name
                )
                logger.info(f"[FileService] Synced update to Qdrant for file {file_id}")
            except Exception as e:
                logger.error(f"[FileService] Failed to sync update to Qdrant for file {file_id}: {e}", exc_info=True)
                raise ExternalServiceException(
                    f"Failed to sync file update to vector index: {str(e)}"
                ) from e

            file_doc.display_name = new_display_name
            file_doc.display_name_unaccented = remove_accents(new_display_name)
            file_doc.custom_metadata = new_metadata

            try:
                await self.file_repo.save(file_doc)
            except Exception as e:
                try:
                    await indexer.update_payload_by_file_id(
                        file_id=file_id,
                        new_metadata=old_metadata.model_dump(mode="json") if metadata_changed and old_metadata else None,
                        file_name=old_display_name if display_name_changed else None
                    )
                except Exception as rollback_error:
                    logger.warning(f"[FileService] Failed to rollback Qdrant update for file {file_id}: {rollback_error}")
                raise AppException(f"Failed to save file update: {str(e)}", status_code=500) from e

            return file_doc
            
        return file_doc

    async def list_files(
        self,
        status: Optional[FileStatus] = None,
        custom_metadata_filter: Optional[Dict[str, Any]] = None,
        keywords: Optional[str] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[list[FileDocument], int]:
        """List files with optional status, keyword, and metadata filters."""
        filters = {}
        if status:
            filters["status"] = status

        if keywords:
            unaccented_kw = remove_accents(keywords)
            filters["$or"] = [
                {"display_name_unaccented": {"$regex": unaccented_kw, "$options": "i"}},
                {"original_filename_unaccented": {"$regex": unaccented_kw, "$options": "i"}}
            ]

        builder = get_filter_builder()
        mongo_filter = await builder.build_mongo_filter(
            metadata_filter=custom_metadata_filter or {},
            mongo_prefix="custom_metadata",
            skip_validation=True
        )
        
        if mongo_filter:
            keyword_or = filters.pop("$or", None)
            filters.update(mongo_filter)
            if keyword_or:
                filters["$and"] = filters.get("$and", []) + [{"$or": keyword_or}]

        return await self.file_repo.list_files(filters=filters, skip=skip, limit=limit)

    async def get_file_by_id(self, file_id: str) -> Optional[FileDocument]:
        """Get a single file by ID."""
        return await self.file_repo.find_by_id(file_id)

    async def get_file_data(self, file_id: str) -> tuple[Any, FileDocument]:
        """Get file bytes and document for download."""
        file_doc = await self.file_repo.find_by_id(file_id)
        if not file_doc:
            raise NotFoundException("File", file_id)

        file_data = await r2_storage.download_file(file_doc.storage_path)
        return file_data, file_doc

_file_service_instance: Optional[FileService] = None

def get_file_service() -> FileService:
    global _file_service_instance
    if _file_service_instance is None:
        _file_service_instance = FileService()
    return _file_service_instance
