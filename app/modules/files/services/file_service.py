import io
import logging
import mimetypes
from pathlib import Path
from typing import Optional, BinaryIO, List, Tuple, Dict, Any, Literal
from bson import ObjectId

from app.core.config import settings
from app.core.exceptions import (
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
        user_role: Optional[str] = None,
        file_format: Literal["original", "markdown"] = "original"
    ) -> tuple[BinaryIO, str, str]:
        """Download a file from Cloudflare R2."""
        file_doc = await self.get_file_by_id(file_id, user_role=user_role)
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
        """Delete file from storage, vector DB, and database (Beanie hard delete)."""
        file_doc = await FileDocument.get(file_id)
        if not file_doc:
            raise NotFoundException("File", file_id)

        # Delete original from Cloudflare R2
        if file_doc.storage_path:
            try:
                await r2_storage.delete_file(file_doc.storage_path)
            except Exception as e:
                logger.warning(f"Failed to delete from Cloudflare R2: {e}")

        # Delete markdown from Cloudflare R2
        if file_doc.markdown_storage_path:
            try:
                await r2_storage.delete_file(file_doc.markdown_storage_path)
            except Exception as e:
                logger.warning(f"Failed to delete markdown artifact from Cloudflare R2: {e}")

        # Delete from Qdrant
        indexer = get_qdrant_indexer()
        await indexer.delete_by_file_id(file_id)

        # Delete from file_toc_trees
        toc_repo = FileTocTreeRepository()
        await toc_repo.delete_by_file_id(file_id)

        # Evict page index cache
        from app.integrations.pageindex.client import get_page_index_client
        page_index_client = get_page_index_client()
        await page_index_client.evict_doc(file_id)

        # Hard delete from MongoDB
        await file_doc.delete()
        logger.info(f"File {file_id} deleted from MongoDB")
        return True

    async def update_file(
        self,
        file_id: str,
        display_name: Optional[str] = None,
        custom_metadata: Optional[Dict[str, Any]] = None
    ) -> Optional[FileDocument]:
        """Update file details (display name and/or metadata) and syncs to Qdrant."""
        file_doc = await FileDocument.get(file_id)
        if not file_doc:
            raise NotFoundException("File", file_id)

        display_name_changed = False
        metadata_changed = False

        if display_name is not None:
            file_doc.display_name = display_name
            file_doc.display_name_unaccented = remove_accents(display_name)
            display_name_changed = True

        if custom_metadata is not None:
            # Validate partial update request DTO
            validator = get_metadata_service()
            is_valid, errors, update_schema = validator.validate_and_parse_file_metadata_update(custom_metadata)
            if not is_valid:
                raise ValidationException(f"Invalid custom metadata: {', '.join(errors)}")

            # Deep merge incoming metadata into existing metadata state
            existing_meta = file_doc.custom_metadata.model_dump() if file_doc.custom_metadata else {}
            
            merged_meta = {}
            if existing_meta.get("enrollment_year"):
                merged_meta["enrollment_year"] = dict(existing_meta["enrollment_year"])
            if existing_meta.get("academic_year"):
                merged_meta["academic_year"] = dict(existing_meta["academic_year"])
            if existing_meta.get("type"):
                merged_meta["type"] = existing_meta["type"]

            update_dict = update_schema.model_dump(exclude_unset=True, by_alias=False) if update_schema else {}

            if "type" in update_dict:
                merged_meta["type"] = update_dict["type"]

            if "enrollment_year" in update_dict:
                inc_ey = update_dict["enrollment_year"] or {}
                exist_ey = merged_meta.get("enrollment_year") or {}
                merged_meta["enrollment_year"] = {
                    "from_year": inc_ey.get("from_year") if inc_ey.get("from_year") is not None else exist_ey.get("from_year", 0),
                    "to_year": inc_ey.get("to_year") if inc_ey.get("to_year") is not None else exist_ey.get("to_year", 9999),
                }

            if "academic_year" in update_dict:
                inc_ay = update_dict["academic_year"] or {}
                exist_ay = merged_meta.get("academic_year") or {}
                merged_meta["academic_year"] = {
                    "from_year": inc_ay.get("from_year") if inc_ay.get("from_year") is not None else exist_ay.get("from_year", 0),
                    "to_year": inc_ay.get("to_year") if inc_ay.get("to_year") is not None else exist_ay.get("to_year", 9999),
                }

            # Validate the final merged metadata state
            clean_merged = {k: v for k, v in merged_meta.items() if v is not None and v != {}}
            is_valid, errors, meta_model = validator.validate_and_parse_file_metadata(clean_merged)
            if not is_valid:
                raise ValidationException(f"Invalid merged metadata: {', '.join(errors)}")
            
            file_doc.custom_metadata = meta_model
            metadata_changed = True

        if display_name_changed or metadata_changed:
            await file_doc.save()

            # Sync update to Qdrant
            try:
                indexer = get_qdrant_indexer()
                qdrant_metadata = file_doc.custom_metadata.to_qdrant_payload() if file_doc.custom_metadata else None
                qdrant_filename = file_doc.display_name if display_name_changed else None
                
                await indexer.update_payload_by_file_id(
                    file_id=file_id,
                    new_metadata=qdrant_metadata,
                    file_name=qdrant_filename
                )
                logger.info(f"[FileService] Synced update to Qdrant for file {file_id}")
            except Exception as e:
                logger.warning(f"[FileService] Failed to sync update to Qdrant for file {file_id}: {e}")

            return file_doc
            
        return file_doc

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
            user_role=user_role,
            skip_validation=True
        )
        
        if mongo_filter:
            keyword_or = filters.pop("$or", None)
            filters.update(mongo_filter)
            if keyword_or:
                filters["$and"] = filters.get("$and", []) + [{"$or": keyword_or}]

        # Run query through Beanie Find
        query = FileDocument.find(filters)
        total = await query.count()
        files = await query.sort("-created_at").skip(skip).limit(limit).to_list()
        return files, total

    async def get_file_by_id(self, file_id: str, user_role: Optional[str] = None) -> Optional[FileDocument]:
        """Get a single file by ID."""
        try:
            return await FileDocument.get(file_id)
        except Exception:
            return None

    async def get_file_data(self, file_id: str, user_role: str = "student") -> tuple[Any, FileDocument]:
        """Get file bytes and document for download."""
        file_doc = await FileDocument.get(file_id)
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
