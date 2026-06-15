from typing import Optional, Dict, Any, List
from app.core.base_repository import BaseRepository
from app.modules.files.toc_tree.models.toc_tree import FileTocTree

class FileTocTreeRepository(BaseRepository):
    """Repository for file TOC trees documents using Beanie ODM."""

    def __init__(self):
        super().__init__("file_toc_trees")

    async def find_by_file_id(self, file_id: str) -> Optional[Dict[str, Any]]:
        doc = await FileTocTree.find_one(FileTocTree.file_id == file_id)
        if doc:
            d = doc.model_dump(by_alias=True)
            d["_id"] = str(doc.id)
            return d
        return None

    async def find_by_file_ids(self, file_ids: list[str]) -> list[Dict[str, Any]]:
        """Find multiple TOC trees by their file IDs."""
        docs = await FileTocTree.find(
            {"file_id": {"$in": file_ids}}
        ).limit(len(file_ids)).to_list()
        
        results = []
        for doc in docs:
            d = doc.model_dump(by_alias=True)
            d["_id"] = str(doc.id)
            results.append(d)
        return results

    async def upsert_by_file_id(self, file_id: str, data: Dict[str, Any]) -> bool:
        """Insert or replace TOC tree for a file."""
        existing = await FileTocTree.find_one(FileTocTree.file_id == file_id)
        if existing:
            for k, v in data.items():
                setattr(existing, k, v)
            await existing.save()
            return True
        
        doc = FileTocTree(file_id=file_id, **data)
        await doc.insert()
        return True

    async def delete_by_file_id(self, file_id: str) -> bool:
        doc = await FileTocTree.find_one(FileTocTree.file_id == file_id)
        if doc:
            await doc.delete()
            return True
        return False
