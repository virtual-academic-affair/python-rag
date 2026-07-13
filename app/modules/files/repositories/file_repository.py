from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from bson import ObjectId

from app.core.base_beanie_repository import BeanieRepository
from app.modules.files.models.file import FileDocument, FileListProjection, FileStatus


class FileRepository(BeanieRepository[FileDocument]):
    """Repository-specific queries for file documents."""

    document_class = FileDocument

    @staticmethod
    def _active_query(filters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if not filters:
            return {"deleted_at": None}
        return {"$and": [{"deleted_at": None}, filters]}

    @staticmethod
    def _deleted_query(filters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        deleted = {"deleted_at": {"$type": "date"}}
        if not filters:
            return deleted
        return {"$and": [deleted, filters]}

    async def find_by_id(self, doc_id: str) -> Optional[FileDocument]:
        if not ObjectId.is_valid(str(doc_id)):
            return None
        return await FileDocument.find_one({"_id": ObjectId(doc_id), "deleted_at": None})

    async def find_by_id_including_deleted(self, doc_id: str) -> Optional[FileDocument]:
        return await super().find_by_id(doc_id)

    async def update_status(self, file_id: str, status: FileStatus) -> bool:
        doc = await self.find_by_id(file_id)
        if not doc:
            return False
        doc.status = status
        await self.save(doc)
        return True

    async def find_by_original_filename(self, original_filename: str) -> Optional[FileDocument]:
        return await FileDocument.find_one({
            "original_filename": original_filename,
            "deleted_at": None,
        })

    async def find_not_ready_by_id(self, file_id: str) -> Optional[FileDocument]:
        try:
            object_id = ObjectId(file_id)
        except Exception:
            return None
        return await FileDocument.find_one(
            FileDocument.id == object_id,
            FileDocument.status != FileStatus.READY,
            FileDocument.deleted_at == None,
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
    ) -> Tuple[List[FileListProjection], int]:
        query = FileDocument.find(self._active_query(filters))
        total = await query.count()
        files = await query.sort("-created_at").skip(skip).limit(limit).project(FileListProjection).to_list()
        return files, total

    async def list_deleted_files(
        self,
        filters: Dict[str, Any],
        skip: int = 0,
        limit: int = 50,
    ) -> Tuple[List[FileListProjection], int]:
        query = FileDocument.find(self._deleted_query(filters))
        total = await query.count()
        files = await query.sort("-deleted_at").skip(skip).limit(limit).project(FileListProjection).to_list()
        return files, total

    async def find_by_display_names(self, display_names: List[str]) -> List[FileDocument]:
        if not display_names:
            return []
        return await FileDocument.find(self._active_query({"display_name": {"$in": display_names}})).to_list()

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

        return await FileDocument.find(self._active_query({"_id": {"$in": object_ids}})).to_list()

    async def find_ids_by_query(self, query: Dict[str, Any]) -> set[str]:
        ids: set[str] = set()
        cursor = FileDocument.get_motor_collection().find(self._active_query(query), {"_id": 1})
        async for row in cursor:
            ids.add(str(row["_id"]))
        return ids

    async def soft_delete(
        self,
        file_id: str,
        *,
        deleted_by: str,
        corpus_node_keys: List[str],
        force_failed: bool = False,
    ) -> bool:
        if not ObjectId.is_valid(str(file_id)):
            return False
        update_fields: Dict[str, Any] = {
            "deleted_at": datetime.now(timezone.utc),
            "deleted_by": deleted_by,
            "deleted_corpus_node_keys": list(dict.fromkeys(corpus_node_keys)),
            "updated_at": datetime.now(timezone.utc),
        }
        if force_failed:
            update_fields["status"] = FileStatus.FAILED.value
        result = await FileDocument.get_motor_collection().update_one(
            {"_id": ObjectId(file_id), "deleted_at": None},
            {"$set": update_fields},
        )
        return result.modified_count == 1

    async def restore(self, file_id: str) -> bool:
        if not ObjectId.is_valid(str(file_id)):
            return False
        now = datetime.now(timezone.utc)
        result = await FileDocument.get_motor_collection().update_one(
            {"_id": ObjectId(file_id), "deleted_at": {"$type": "date"}},
            {
                "$set": {
                    "deleted_at": None,
                    "deleted_by": None,
                    "deleted_corpus_node_keys": [],
                    "updated_at": now,
                }
            },
        )
        return result.modified_count == 1
