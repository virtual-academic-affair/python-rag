from typing import Optional, Dict, Any
from app.repositories.base import BaseRepository
from app.core.database import Database

class FileTocTreeRepository(BaseRepository):
    """Repository for file TOC trees documents."""

    def __init__(self):
        super().__init__(Database.FILE_TOC_TREES)

    async def find_by_file_id(self, file_id: str) -> Optional[Dict[str, Any]]:
        return await self.find_one({"file_id": file_id})

    async def upsert_by_file_id(self, file_id: str, data: Dict[str, Any]) -> bool:
        """Insert or replace TOC tree for a file."""
        existing = await self.find_by_file_id(file_id)
        if existing:
            return await self.update_by_id(existing["_id"], data)
        
        await self.create({**data, "file_id": file_id})
        return True

    async def delete_by_file_id(self, file_id: str) -> bool:
        return await self.delete({"file_id": file_id})
