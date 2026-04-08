"""
File Chunk Repository - MongoDB operations for parsed chunks.
"""

from typing import Optional, List, Dict, Any

from app.repositories.base import BaseRepository
from app.core.database import Database


class FileChunkRepository(BaseRepository):
    """Repository for file chunk documents."""

    def __init__(self):
        super().__init__(Database.FILE_CHUNKS)

    async def find_by_file_id(
        self,
        file_id: str,
        skip: int = 0,
        limit: int = 500,
    ) -> List[Dict[str, Any]]:
        return await self.find_many(
            query={"file_id": file_id},
            skip=skip,
            limit=limit,
            sort=[("chunk_index", 1)],
        )

    async def count_by_file_id(self, file_id: str) -> int:
        return await self.count({"file_id": file_id})

    async def delete_by_file_id(self, file_id: str) -> int:
        return await self.delete_many({"file_id": file_id})

    async def create_many(self, documents: List[Dict[str, Any]]) -> int:
        """Bulk insert chunks. Returns inserted count."""
        if not documents:
            return 0

        for doc in documents:
            if "created_at" in doc:
                doc.pop("created_at")
            if "updated_at" in doc:
                doc.pop("updated_at")

        result = await self.collection.insert_many(documents)
        return len(result.inserted_ids)

    async def find_one_by_chunk_id(self, chunk_id: str) -> Optional[Dict[str, Any]]:
        return await self.find_one({"chunk_id": chunk_id})

