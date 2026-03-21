"""
Store Repository - Database operations for Gemini File Search stores.
"""

from typing import Optional, List, Dict, Any
import logging

from app.repositories.base import BaseRepository
from app.core.database import Database
from app.core.exceptions import ConflictException

logger = logging.getLogger(__name__)


class StoreRepository(BaseRepository):
    """Repository for store documents."""
    
    def __init__(self):
        super().__init__(Database.STORES)
    
    async def find_by_store_name(self, store_name: str) -> Optional[Dict[str, Any]]:
        """
        Find store by Gemini store name.
        
        Args:
            store_name: Gemini store name (fileSearchStores/xxx)
            
        Returns:
            Store document or None
        """
        return await self.find_one({"store_name": store_name})
    
    async def find_default_store(self) -> Optional[Dict[str, Any]]:
        """
        Find the default store.
        
        Returns:
            Default store document or None
        """
        return await self.find_one({"is_default": True})
    
    async def create_store(self, store_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create new store.
        
        Args:
            store_data: Store data (must include store_name, display_name)
            
        Returns:
            Created store document
            
        Raises:
            ConflictException: If store_name already exists
        """
        # Check for duplicate store_name
        existing = await self.find_by_store_name(store_data["store_name"])
        if existing:
            raise ConflictException(f"Store name '{store_data['store_name']}' already exists")
        
        return await self.create(store_data)
    
    async def set_as_default(self, store_id: str) -> bool:
        """
        Set store as default (unset others first).
        
        Args:
            store_id: Store ID (MongoDB _id as string)
            
        Returns:
            True if successful
        """
        # Unset all other defaults
        await self.collection.update_many(
            {"is_default": True},
            {"$set": {"is_default": False}}
        )
        
        # Set this one as default
        return await self.update_by_id(store_id, {"is_default": True})
    
    async def update_statistics(
        self,
        store_id: str,
        file_count: int,
        total_size: int
    ) -> bool:
        """
        Update store statistics from Gemini.
        
        Args:
            store_id: Store ID (MongoDB _id as string)
            file_count: activeDocumentsCount from Gemini
            total_size: sizeBytes from Gemini
            
        Returns:
            True if updated
        """
        return await self.update_by_id(store_id, {
            "file_count": file_count,
            "total_size": total_size
        })
    
    async def count_all(self) -> int:
        """
        Count all stores.
        
        Returns:
            Number of stores
        """
        return await self.count({})

    async def list_stores(self, skip: int = 0, limit: int = 100) -> tuple[List[Dict[str, Any]], int]:
        """List stores with pagination."""
        docs = await self.find_many({}, skip=skip, limit=limit)
        total = await self.count_all()
        return docs, total

    async def update_display_name(self, store_id: str, display_name: str) -> Optional[Dict[str, Any]]:
        """Update store display name."""
        updated = await self.update_by_id(store_id, {"display_name": display_name})
        if updated:
            return await self.find_by_id(store_id)
        return None
