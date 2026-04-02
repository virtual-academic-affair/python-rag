"""
File Repository - Database operations for file documents.
"""

from typing import Optional, List, Dict, Any
import logging

from app.repositories.base import BaseRepository
from app.core.database import Database
from app.models.enums import FileStatus

logger = logging.getLogger(__name__)


class FileRepository(BaseRepository):
    """Repository for file documents."""
    
    def __init__(self):
        super().__init__(Database.FILES)
    
    async def find_by_indexed_name(self, indexed_document_name: str) -> Optional[Dict[str, Any]]:
        """Find file by indexed document name (legacy DB alias: gemini_document_name)."""
        return await self.find_one({"gemini_document_name": indexed_document_name})

    async def find_by_gemini_name(self, gemini_document_name: str) -> Optional[Dict[str, Any]]:
        """Backward-compatible alias for find_by_indexed_name."""
        return await self.find_by_indexed_name(gemini_document_name)

    async def find_by_store(
        self,
        store_id: str,
        skip: int = 0,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """
        Find files in a specific store.
        
        Args:
            store_id: Store ID (MongoDB ObjectId as string)
            skip: Number to skip
            limit: Maximum results
            
        Returns:
            List of file documents
        """
        query = {"store_id": store_id}
        return await self.find_many(
            query=query,
            skip=skip,
            limit=limit,
            sort=[("created_at", -1)]
        )
    
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
    
    async def update_indexed_info(
        self,
        file_id: str,
        indexed_document_name: str,
        status: FileStatus = FileStatus.ACTIVE,
    ) -> bool:
        """Update indexed document info after successful indexing."""
        return await self.update_by_id(
            file_id,
            {
                "gemini_document_name": indexed_document_name,
                "status": status.value,
            },
        )

    async def update_gemini_info(
        self,
        file_id: str,
        gemini_document_name: str,
        status: FileStatus = FileStatus.ACTIVE,
    ) -> bool:
        """Backward-compatible alias for update_indexed_info."""
        return await self.update_indexed_info(file_id, gemini_document_name, status)

    async def count_by_store(self, store_id: str) -> int:
        """
        Count files in a store.
        
        Args:
            store_id: Store ID (MongoDB ObjectId as string)
            
        Returns:
            File count
        """
        query = {"store_id": store_id}
        return await self.count(query)
    
    async def delete_by_store(self, store_id: str) -> int:
        """
        Delete all files in a store.
        
        Args:
            store_id: Store ID (MongoDB ObjectId as string)
            
        Returns:
            Number of deleted files
        """
        query = {"store_id": store_id}
        return await self.delete_many(query)
    
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
