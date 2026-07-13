import logging
from pathlib import Path
from typing import Optional, BinaryIO, Dict, Any, Literal

from app.core.exceptions import (
    AppException,
    ConflictException,
    NotFoundException,
    StorageException,
    ValidationException,
)
from app.modules.files.models.file import FileDocument, FileListProjection, FileStatus
from app.modules.files.repositories.file_repository import FileRepository
from app.integrations.storage.client import r2_storage
from app.modules.metadata.services.metadata_service import get_metadata_service
from app.utils.text_utils import remove_accents
from app.modules.files.toc_tree.repositories.toc_tree_repository import FileTocTreeRepository
from app.modules.metadata.utils.filter_builder import get_filter_builder
from app.modules.rag.ingestion.corpus_linker import get_corpus_linker
from app.modules.files.services.file_upload_service import FileUploadMixin

logger = logging.getLogger(__name__)

class FileService(FileUploadMixin):
    """
    Service for file management operations.
    Coordinates between Cloudflare R2 storage, MongoDB (Beanie), and Corpus Tree.
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

    async def delete_file(self, file_id: str, deleted_by: str) -> bool:
        """Soft-delete a file while retaining storage and TOC artifacts for restore."""
        file_doc = await self.file_repo.find_by_id_including_deleted(file_id)
        if not file_doc:
            raise NotFoundException("File", file_id)

        if file_doc.deleted_at is None:
            from app.modules.corpus.services.corpus_service import get_corpus_service

            node_keys = await get_corpus_service().get_payload_node_keys("file", file_id)
            await self.file_repo.soft_delete(
                file_id,
                deleted_by=deleted_by,
                corpus_node_keys=node_keys,
                force_failed=file_doc.status in (FileStatus.UPLOADING, FileStatus.PROCESSING),
            )

        # Idempotent cleanup: retrying DELETE repairs any previous partial unindex/cache eviction.
        await get_corpus_linker().unindex_file(file_id)

        from app.integrations.pageindex.client import get_page_index_client

        await get_page_index_client().evict_doc(file_id)
        logger.info("File %s soft-deleted by %s", file_id, deleted_by)
        return True

    async def restore_file(self, file_id: str) -> FileDocument:
        file_doc = await self.file_repo.find_by_id_including_deleted(file_id)
        if not file_doc:
            raise NotFoundException("File", file_id)
        if file_doc.deleted_at is None:
            raise ConflictException("File is not deleted")

        duplicate = await self.file_repo.find_by_original_filename(file_doc.original_filename)
        if duplicate:
            raise ConflictException(f"Active file '{file_doc.original_filename}' already exists")
        if not file_doc.storage_path or not await r2_storage.file_exists(file_doc.storage_path):
            raise ConflictException("Original file artifact is missing")

        toc_tree = None
        if file_doc.status == FileStatus.READY:
            toc_tree = await FileTocTreeRepository().find_by_file_id(file_id)
            if not file_doc.markdown_storage_path or not await r2_storage.file_exists(file_doc.markdown_storage_path):
                raise ConflictException("Markdown artifact is missing")
            if not toc_tree:
                raise ConflictException("TOC tree artifact is missing")

        reindexed = False
        try:
            if file_doc.status == FileStatus.READY:
                from app.modules.corpus.services.corpus_service import get_corpus_service

                corpus_svc = get_corpus_service()
                valid_keys = await corpus_svc.existing_node_keys(file_doc.deleted_corpus_node_keys)
                if valid_keys:
                    await corpus_svc.reindex_payload("file", file_id, valid_keys)
                else:
                    node_keys = await get_corpus_linker().index_file(
                        file_id,
                        display_name=file_doc.display_name or "",
                        doc_description=(toc_tree.doc_description if toc_tree else "") or "",
                        toc_headings=file_doc.table_of_contents or [],
                    )
                    if not node_keys:
                        raise ConflictException("File could not be assigned to a Corpus topic")
                reindexed = True

            if not await self.file_repo.restore(file_id):
                raise ConflictException("File restore state changed concurrently")
        except Exception:
            if reindexed:
                await get_corpus_linker().unindex_file(file_id)
            raise

        restored = await self.file_repo.find_by_id(file_id)
        if not restored:
            raise AppException("File restore completed but active record could not be loaded", status_code=500)
        return restored

    async def purge_file(self, file_id: str) -> bool:
        file_doc = await self.file_repo.find_by_id_including_deleted(file_id)
        if not file_doc:
            raise NotFoundException("File", file_id)
        if file_doc.deleted_at is None:
            raise ConflictException("File must be soft-deleted before purge")

        await get_corpus_linker().unindex_file(file_id)
        from app.integrations.pageindex.client import get_page_index_client

        await get_page_index_client().evict_doc(file_id)
        await FileTocTreeRepository().delete_by_file_id(file_id)

        for storage_path in (file_doc.storage_path, file_doc.markdown_storage_path):
            if storage_path and not await r2_storage.delete_file(storage_path):
                raise StorageException(f"Failed to purge R2 object: {storage_path}")

        await self.file_repo.delete(file_doc)
        logger.info("File %s permanently purged", file_id)
        return True

    async def update_file(
        self,
        file_id: str,
        display_name: Optional[str] = None,
        custom_metadata: Optional[Dict[str, Any]] = None,
        lecturer_only: Optional[bool] = None,
    ) -> Optional[FileDocument]:
        """Update file details (display name, metadata, and/or lecturer_only flag)."""
        file_doc = await self.file_repo.find_by_id(file_id)
        if not file_doc:
            raise NotFoundException("File", file_id)

        changed = False

        if display_name is not None and display_name != file_doc.display_name:
            file_doc.display_name = display_name
            file_doc.display_name_unaccented = remove_accents(display_name)
            changed = True

        if custom_metadata is not None:
            validator = get_metadata_service()
            is_valid, errors, meta_model = validator.merge_file_metadata_update(
                existing=file_doc.custom_metadata,
                incoming_update=custom_metadata,
            )
            if not is_valid:
                raise ValidationException(f"Invalid merged metadata: {', '.join(errors)}")
            if meta_model != file_doc.custom_metadata:
                file_doc.custom_metadata = meta_model
                changed = True

        if lecturer_only is not None and lecturer_only != file_doc.lecturer_only:
            file_doc.lecturer_only = lecturer_only
            changed = True

        if changed:
            try:
                await self.file_repo.save(file_doc)
            except Exception as e:
                raise AppException(f"Failed to save file update: {str(e)}", status_code=500) from e

        return file_doc

    async def list_files(
        self,
        status: Optional[FileStatus] = None,
        custom_metadata_filter: Optional[Dict[str, Any]] = None,
        keywords: Optional[str] = None,
        role_filter: Optional[Dict[str, Any]] = None,
        deleted_only: bool = False,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[list[FileListProjection], int]:
        """List files with optional status, keyword, metadata, and role-based filters."""
        filters = {}
        if status:
            filters["status"] = status

        if role_filter:
            filters.update(role_filter)

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

        if deleted_only:
            return await self.file_repo.list_deleted_files(filters=filters, skip=skip, limit=limit)
        return await self.file_repo.list_files(filters=filters, skip=skip, limit=limit)

    async def find_ids_for_corpus(
        self,
        metadata_filter: Optional[Dict[str, Any]],
        user_role: Optional[str],
        lecturer_only: Optional[bool] = None,
    ) -> set[str]:
        """Return READY file IDs allowed for corpus traversal."""
        query: Dict[str, Any] = {
            "status": FileStatus.READY.value,
            "deleted_at": None,
        }
        privileged = (user_role or "") in {"admin", "lecture"}
        if lecturer_only is not None and privileged:
            query["lecturer_only"] = lecturer_only
        elif not privileged:
            query["lecturer_only"] = {"$ne": True}
        query.update(
            await get_filter_builder().build_mongo_filter(
                metadata_filter or {},
                mongo_prefix="custom_metadata",
            )
        )
        return await self.file_repo.find_ids_by_query(query)

    async def get_files_by_ids(self, file_ids: list[str]) -> list[FileDocument]:
        return await self.file_repo.find_by_ids(file_ids)

    async def get_file_by_id(self, file_id: str) -> Optional[FileDocument]:
        """Get a single file by ID."""
        return await self.file_repo.find_by_id(file_id)

    async def get_file_by_id_including_deleted(self, file_id: str) -> Optional[FileDocument]:
        return await self.file_repo.find_by_id_including_deleted(file_id)

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
