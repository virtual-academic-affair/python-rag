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

    async def find_by_ids(self, file_ids: List[str]) -> List[Dict[str, Any]]:
        """
        Find files by list of IDs.
        
        Args:
            file_ids: List of file IDs (strings)
            
        Returns:
            List of file documents
        """
        if not file_ids:
            return []
            
        object_ids = []
        for fid in file_ids:
            try:
                object_ids.append(self._to_object_id(fid))
            except ValueError:
                continue
                
        if not object_ids:
            return []
            
        query = {"_id": {"$in": object_ids}}
        return await self.find_many(query=query, skip=0, limit=len(object_ids))
