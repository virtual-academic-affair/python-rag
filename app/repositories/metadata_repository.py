"""
Metadata Type Repository - Database operations for metadata type definitions.
"""

from typing import Optional, List, Dict, Any
import logging

from app.repositories.base import BaseRepository
from app.core.database import Database
from app.core.exceptions import ConflictException, NotFoundException

logger = logging.getLogger(__name__)


class MetadataRepository(BaseRepository):
    """Repository for metadata type documents."""
    
    def __init__(self):
        super().__init__(Database.METADATA_TYPES)
    
    async def find_by_key(self, key: str) -> Optional[Dict[str, Any]]:
        """
        Find metadata type by key.
        
        Args:
            key: Metadata key (e.g., "department")
            
        Returns:
            Metadata type document or None
        """
        return await self.find_one({"key": key})
    
    async def find_all(
        self,
        skip: int = 0,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        Find all metadata types.
        
        Args:
            skip: Number to skip
            limit: Maximum results
            
        Returns:
            List of metadata type documents
        """
        return await self.find_many(
            query={},
            skip=skip,
            limit=limit,
            sort=[("key", 1)]
        )
    
    async def create_metadata_type(self, metadata_type: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create new metadata type.
        
        Args:
            metadata_type: Metadata type data (key, value_type, etc.)
            
        Returns:
            Created metadata type document
            
        Raises:
            ConflictException: If key already exists
        """
        existing = await self.find_by_key(metadata_type["key"])
        if existing:
            raise ConflictException(f"Metadata type with key '{metadata_type['key']}' already exists")
        
        return await self.create(metadata_type)
    
    async def update_by_key(
        self,
        key: str,
        update_data: Dict[str, Any]
    ) -> bool:
        """
        Update metadata type by key.
        
        Args:
            key: Metadata key
            update_data: Fields to update
            
        Returns:
            True if updated
            
        Raises:
            NotFoundException: If key not found
        """
        existing = await self.find_by_key(key)
        if not existing:
            raise NotFoundException("Metadata type", key)
        
        return await self.update(
            query={"key": key},
            update_data=update_data
        )
    
    async def delete_by_key(self, key: str) -> bool:
        """
        Delete metadata type by key (hard delete).
        
        Args:
            key: Metadata key
            
        Returns:
            True if deleted
            
        Raises:
            NotFoundException: If key not found
        """
        existing = await self.find_by_key(key)
        if not existing:
            raise NotFoundException("Metadata type", key)
        
        return await self.delete({"key": key})
    
    async def get_all_keys(self) -> List[str]:
        """
        Get list of all metadata keys.
        
        Returns:
            List of metadata keys
        """
        metadata_types = await self.find_all(limit=1000)
        return [mt["key"] for mt in metadata_types]
