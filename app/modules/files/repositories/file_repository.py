from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from bson import ObjectId

from app.core.base_beanie_repository import BeanieRepository
from app.modules.files.models.file import FileDocument, FileStatus


class FileRepository(BeanieRepository[FileDocument]):
    """Repository-specific queries for file documents."""

    document_class = FileDocument

    async def update_status(self, file_id: str, status: FileStatus) -> bool:
        doc = await self.find_by_id(file_id)
        if not doc:
            return False
        doc.status = status
        await self.save(doc)
        return True

    async def find_by_original_filename(self, original_filename: str) -> Optional[FileDocument]:
        return await FileDocument.find_one(FileDocument.original_filename == original_filename)

    async def find_not_ready_by_id(self, file_id: str) -> Optional[FileDocument]:
        try:
            object_id = ObjectId(file_id)
        except Exception:
            return None
        return await FileDocument.find_one(
            FileDocument.id == object_id,
            FileDocument.status != FileStatus.READY,
        )

    async def mark_processing(self, file_id: str) -> Optional[FileDocument]:
        doc = await self.find_by_id(file_id)
        if not doc:
            return None
        doc.status = FileStatus.PROCESSING
        return await self.save(doc)

    async def mark_failed(self, file_id: str) -> bool:
        doc = await self.find_by_id(file_id)
        if not doc:
            return False
        doc.status = FileStatus.FAILED
        await self.save(doc)
        return True

    async def mark_ready(
        self,
        file_id: str,
        markdown_storage_path: str,
        markdown_file_size: int,
        table_of_contents: list,
    ) -> Optional[FileDocument]:
        doc = await self.find_not_ready_by_id(file_id)
        if not doc:
            return None
        doc.markdown_storage_path = markdown_storage_path
        doc.markdown_file_size = markdown_file_size
        doc.table_of_contents = table_of_contents
        doc.status = FileStatus.READY
        return await self.save(doc)

    async def list_files(
        self,
        filters: Dict[str, Any],
        skip: int = 0,
        limit: int = 50,
    ) -> Tuple[List[FileDocument], int]:
        query = FileDocument.find(filters)
        total = await query.count()
        files = await query.sort("-created_at").skip(skip).limit(limit).to_list()
        return files, total

    async def find_by_display_names(self, display_names: List[str]) -> List[FileDocument]:
        if not display_names:
            return []
        return await FileDocument.find({"display_name": {"$in": display_names}}).to_list()

    async def find_by_ids(self, file_ids: List[str]) -> List[FileDocument]:
        if not file_ids:
            return []

        object_ids = []
        for fid in file_ids:
            try:
                object_ids.append(ObjectId(fid))
            except Exception:
                continue

        if not object_ids:
            return []

        return await FileDocument.find({"_id": {"$in": object_ids}}).to_list()
