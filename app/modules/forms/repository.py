from typing import List, Dict, Any, Optional
from pymongo import DESCENDING
from app.repositories.base import BaseRepository
from app.core.database import Database

class FormRepository(BaseRepository):
    def __init__(self):
        super().__init__(Database.FORMS)

    async def find_all_forms(self, skip: int = 0, limit: int = 100, search: Optional[str] = None) -> List[Dict[str, Any]]:
        query = {}
        if search:
            query["documentType"] = {"$regex": search, "$options": "i"}
        return await self.find_many(
            query=query,
            skip=skip,
            limit=limit,
            sort=[("createdAt", DESCENDING)]
        )

    async def count_forms(self, search: Optional[str] = None) -> int:
        query = {}
        if search:
            query["documentType"] = {"$regex": search, "$options": "i"}
        return await self.count(query=query)

    async def find_one_by_content_link(self, document_type: str, content_link: str) -> Optional[Dict[str, Any]]:
        return await self.find_one({
            "documentType": document_type,
            "contentLink": content_link
        })
