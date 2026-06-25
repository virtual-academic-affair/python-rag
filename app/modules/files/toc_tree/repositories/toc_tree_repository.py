from __future__ import annotations

from typing import List, Optional

from app.core.base_beanie_repository import BeanieRepository
from app.modules.files.toc_tree.models.toc_tree import FileTocTree, TocTreeUpsertData


class FileTocTreeRepository(BeanieRepository[FileTocTree]):
    """Repository-specific queries for file TOC tree documents."""

    document_class = FileTocTree

    async def find_by_file_id(self, file_id: str) -> Optional[FileTocTree]:
        return await FileTocTree.find_one(FileTocTree.file_id == file_id)

    async def find_by_file_ids(self, file_ids: list[str]) -> List[FileTocTree]:
        if not file_ids:
            return []
        return await FileTocTree.find({"file_id": {"$in": file_ids}}).limit(len(file_ids)).to_list()

    async def upsert_by_file_id(self, file_id: str, data: TocTreeUpsertData) -> bool:
        existing = await self.find_by_file_id(file_id)
        update_data = {
            "doc_name": data.doc_name,
            "doc_description": data.doc_description,
            "line_count": data.line_count,
            "structure": data.structure,
            "markdown_storage_path": data.markdown_storage_path,
        }
        if existing:
            for key, value in update_data.items():
                setattr(existing, key, value)
            await self.save(existing)
            return True

        doc = FileTocTree(file_id=file_id, **update_data)
        await self.create(doc)
        return True

    async def delete_by_file_id(self, file_id: str) -> bool:
        doc = await self.find_by_file_id(file_id)
        if not doc:
            return False
        await self.delete(doc)
        return True
