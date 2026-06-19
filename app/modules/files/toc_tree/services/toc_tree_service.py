from typing import Optional, Dict, Any
import logging

from app.core.exceptions import NotFoundException
from app.modules.files.toc_tree.models.toc_tree import FileTocTree
from app.modules.files.toc_tree.repositories.toc_tree_repository import FileTocTreeRepository

logger = logging.getLogger(__name__)

class TocTreeService:
    def __init__(self):
        self._repo = FileTocTreeRepository()

    async def get_toc_tree(self, file_id: str) -> FileTocTree:
        """Retrieve the Table of Contents tree for a given file_id."""
        logger.info(f"Retrieving TOC tree for file: {file_id}")
        toc_data = await self._repo.find_by_file_id(file_id)
        if not toc_data:
            raise NotFoundException("TOC Tree", file_id)
        return toc_data

    async def upsert_toc_tree(self, file_id: str, data: Dict[str, Any]) -> bool:
        """Insert or replace the TOC tree for a given file_id."""
        logger.info(f"Upserting TOC tree for file: {file_id}")
        return await self._repo.upsert_by_file_id(file_id, data)

_toc_tree_service_instance: Optional[TocTreeService] = None

def get_toc_tree_service() -> TocTreeService:
    """Get the singleton instance of TocTreeService."""
    global _toc_tree_service_instance
    if _toc_tree_service_instance is None:
        _toc_tree_service_instance = TocTreeService()
    return _toc_tree_service_instance
