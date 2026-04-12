"""
File Repository - Database operations for file documents.
"""

from typing import Optional, List, Dict, Any
import logging

from app.repositories.base import BaseRepository
from app.core.database import Database
from app.modules.files.models import FileStatus

logger = logging.getLogger(__name__)


class FileRepository(BaseRepository):
    """Repository for file documents."""
    
    def __init__(self):
        super().__init__(Database.FILES)
    
    async def find_with_filters(
        self,
        filters: Dict[str, Any],
        skip: int = 0,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """
        Find files with filters.
        
        Args:
            filters: MongoDB query filters
            skip: Number to skip
            limit: Maximum results
            
        Returns:
            List of file documents
        """
        return await self.find_many(
            query=filters,
            skip=skip,
            limit=limit,
            sort=[("created_at", -1)]
        )
    
    async def count_with_filters(self, filters: Dict[str, Any]) -> int:
        """
        Count files matching filters.
        
        Args:
            filters: MongoDB query filters
            
        Returns:
            Count of matching files
        """
        return await self.count(filters)
    
    async def update_status(
        self,
        file_id: str,
        status: FileStatus,
    ) -> bool:
        """
        Update file status.
        
        Args:
            file_id: File ID (MongoDB _id as string)
            status: New status
            
        Returns:
            True if updated
        """
        return await self.update_by_id(file_id, {"status": status.value})
    
    async def find_by_display_names(self, display_names: List[str]) -> List[Dict[str, Any]]:
        """
        Find files by list of display names.
        
        Args:
            display_names: List of display names to search
            
        Returns:
            List of file documents matching the display names
        """
        if not display_names:
            return []
        query = {"display_name": {"$in": display_names}}
        return await self.find_many(query=query, skip=0, limit=len(display_names))
