"""
Store Service - Business logic for Gemini File Search store management.
"""

import asyncio
import logging
from typing import Optional

from app.core.config import settings
from app.core.exceptions import (
    GeminiException,
    ConflictException,
    NotFoundException,
    ValidationException,
)
from app.models.database import StoreDocument
from app.repositories.store_repository import StoreRepository
from app.repositories.file_repository import FileRepository
from app.storage.minio_client import minio_storage

logger = logging.getLogger(__name__)


def _to_store_model(doc: dict) -> Optional[StoreDocument]:
    """Convert dict to StoreDocument."""
    if not doc:
        return None
    return StoreDocument(**doc)


class StoreService:
    """Service for Gemini File Search store management."""
    
    def __init__(self):
        self._store_repo = None
        self._file_repo = None
        self._gemini_client = None
    
    @property
    def gemini_client(self):
        """Share Gemini client from GeminiClient singleton."""
        if self._gemini_client is None:
            from app.services.rag.gemini_client import gemini_client
            self._gemini_client = gemini_client.client
        return self._gemini_client
    
    @property
    def store_repo(self) -> StoreRepository:
        if self._store_repo is None:
            self._store_repo = StoreRepository()
        return self._store_repo
    
    @property
    def file_repo(self) -> FileRepository:
        if self._file_repo is None:
            self._file_repo = FileRepository()
        return self._file_repo
    
    async def create_store(
        self,
        display_name: str,
        set_as_default: bool = False,
    ) -> StoreDocument:
        """
        Create a new Gemini File Search store.
        
        Args:
            display_name: Display name for the store (passed to Gemini)
            set_as_default: Set as default store for uploads
            
        Returns:
            Created StoreDocument
        """
        try:
            # Create store in Gemini API
            logger.info(f"Creating Gemini store with display_name: {display_name}")
            gemini_store = await asyncio.to_thread(
                self.gemini_client.file_search_stores.create,
                config={"display_name": display_name}
            )
            
            # gemini_store.name format: fileSearchStores/xxx-123abc
            store_name = gemini_store.name
            
            # Create store document in MongoDB
            store_data = {
                "store_name": store_name,
                "display_name": display_name,
                "file_count": 0,
                "total_size": 0,
                "is_default": set_as_default,
            }
            
            created = await self.store_repo.create_store(store_data)
            
            if set_as_default:
                await self.store_repo.set_as_default(created["_id"])
            
            logger.info(f"Store created: {store_name}")
            return _to_store_model(created)
            
        except ConflictException:
            raise
        except Exception as e:
            logger.error(f"Store creation failed: {e}", exc_info=True)
            raise GeminiException(f"Failed to create store: {str(e)}")
    
    async def get_store(self, store_id: str) -> Optional[StoreDocument]:
        """Get a store by MongoDB _id."""
        store_dict = await self.store_repo.find_by_id(store_id)
        return _to_store_model(store_dict)
    
    async def get_store_by_name(self, store_name: str) -> Optional[StoreDocument]:
        """Get a store by Gemini store name."""
        store_dict = await self.store_repo.find_by_store_name(store_name)
        return _to_store_model(store_dict)
    
    async def get_default_store(self) -> Optional[StoreDocument]:
        """Get the default store."""
        store_dict = await self.store_repo.find_default_store()
        return _to_store_model(store_dict)
    
    async def list_stores(
        self,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[list[StoreDocument], int]:
        """List stores with pagination."""
        store_dicts = await self.store_repo.find_many({}, skip, limit, sort=[("created_at", -1)])
        total = await self.store_repo.count({})
        
        stores = [_to_store_model(s) for s in store_dicts]
        return stores, total
    
    async def update_store(
        self, 
        store_id: str, 
        display_name: Optional[str] = None,
        is_default: Optional[bool] = None,
    ) -> StoreDocument:
        """Update store properties."""
        store_dict = await self.store_repo.find_by_id(store_id)
        if not store_dict:
            raise NotFoundException("Store", store_id)
        
        updates = {}
        
        # Handle set_as_default
        if is_default is True:
            await self.store_repo.set_as_default(store_id)
        elif is_default is False:
            updates["is_default"] = False
        
        # Update other fields
        if display_name:
            updates["display_name"] = display_name
        
        if updates:
            await self.store_repo.update_by_id(store_id, updates)
        
        updated = await self.store_repo.find_by_id(store_id)
        logger.info(f"Store updated: {store_id}")
        return _to_store_model(updated)
    
    async def delete_store(self, store_id: str, force: bool = False) -> bool:
        """
        Delete a store (hard delete).
        
        Args:
            store_id: Store ID (MongoDB _id)
            force: If True, delete even if store has files
            
        Returns:
            True if deleted
        """
        store_dict = await self.store_repo.find_by_id(store_id)
        if not store_dict:
            raise NotFoundException("Store", store_id)
        
        store_name = store_dict["store_name"]
        file_count = await self.file_repo.count_by_store(store_id)
        
        if file_count > 0 and not force:
            raise ValidationException(f"Store has {file_count} files. Use force=true to delete.")
        
        # Delete from Gemini API (with force to delete documents)
        try:
            await asyncio.to_thread(
                self.gemini_client.file_search_stores.delete, 
                name=store_name,
                config={"force": True}
            )
            logger.info(f"Deleted store from Gemini: {store_name}")
        except Exception as e:
            logger.warning(f"Gemini store deletion failed: {e}")
        
        # Delete files from MinIO and MongoDB
        if file_count > 0:
            # Get all files in store to delete from MinIO
            files = await self.file_repo.find_by_store(store_id, skip=0, limit=10000)
            
            # Delete each file from MinIO
            for file_dict in files:
                storage_path = file_dict.get("storage_path")
                if storage_path:
                    try:
                        await minio_storage.delete_file(storage_path)
                        logger.info(f"Deleted MinIO file: {storage_path}")
                    except Exception as e:
                        logger.warning(f"Failed to delete MinIO file {storage_path}: {e}")
            
            # Delete files from MongoDB (hard delete)
            deleted_files = await self.file_repo.delete_by_store(store_id)
            logger.info(f"Deleted {deleted_files} files from store {store_id}")
        
        # Delete store from MongoDB (hard delete)
        await self.store_repo.delete_by_id(store_id)
        
        logger.info(f"Store deleted: {store_id}")
        return True
    
    async def sync_store_stats(self, store_id: str) -> StoreDocument:
        """
        Sync store statistics from Gemini API.
        
        Args:
            store_id: Store ID (MongoDB _id)
            
        Returns:
            Updated StoreDocument
        """
        store_dict = await self.store_repo.find_by_id(store_id)
        if not store_dict:
            raise NotFoundException("Store", store_id)
        
        store_name = store_dict["store_name"]
        
        try:
            # Get store info from Gemini
            gemini_store = await asyncio.to_thread(
                self.gemini_client.file_search_stores.get,
                name=store_name,
            )
            
            # Update statistics
            file_count = int(getattr(gemini_store, "active_documents_count", 0) or 0)
            total_size = int(getattr(gemini_store, "size_bytes", 0) or 0)
            
            await self.store_repo.update_statistics(store_id, file_count, total_size)
            
            updated = await self.store_repo.find_by_id(store_id)
            logger.info(f"Store stats synced: {store_name} ({file_count} files, {total_size} bytes)")
            return _to_store_model(updated)
            
        except Exception as e:
            logger.error(f"Failed to sync store stats: {e}")
            raise GeminiException(f"Failed to sync store stats: {str(e)}")
    
    async def list_gemini_stores(self) -> list[dict]:
        """List all stores directly from Gemini API."""
        try:
            stores = await asyncio.to_thread(self.gemini_client.file_search_stores.list)
            return [
                {
                    "store_name": s.name,
                    "display_name": getattr(s, "display_name", None),
                    "active_documents_count": getattr(s, "active_documents_count", 0),
                    "size_bytes": getattr(s, "size_bytes", 0),
                    "create_time": str(getattr(s, "create_time", "")),
                    "update_time": str(getattr(s, "update_time", "")),
                }
                for s in stores
            ]
        except Exception as e:
            raise GeminiException(f"Failed to list Gemini stores: {str(e)}")
    
    async def delete_all_stores(self) -> int:
        """
        Delete all stores (Gemini + MongoDB + all files).
        
        Returns:
            Number of stores deleted
        """
        stores, _ = await self.list_stores(skip=0, limit=10000)
        deleted_count = 0
        
        for store in stores:
            try:
                await self.delete_store(str(store.id), force=True)
                deleted_count += 1
            except Exception as e:
                logger.error(f"Failed to delete store {store.id}: {e}")
        
        logger.info(f"Deleted {deleted_count} stores (full delete)")
        return deleted_count
    
    async def delete_all_gemini_stores(self) -> int:
        """
        Delete all stores from Gemini API only.
        Does NOT delete from MongoDB or MinIO.
        
        Returns:
            Number of Gemini stores deleted
        """
        try:
            gemini_stores = await self.list_gemini_stores()
            deleted_count = 0
            
            for store in gemini_stores:
                try:
                    await asyncio.to_thread(
                        self.gemini_client.file_search_stores.delete,
                        name=store["store_name"],
                        config={"force": True}
                    )
                    deleted_count += 1
                    logger.info(f"Deleted Gemini store: {store['store_name']}")
                except Exception as e:
                    logger.error(f"Failed to delete Gemini store {store['store_name']}: {e}")
            
            logger.info(f"Deleted {deleted_count} Gemini stores")
            return deleted_count
            
        except Exception as e:
            logger.error(f"Failed to delete all Gemini stores: {e}")
            raise GeminiException(f"Failed to delete all Gemini stores: {str(e)}")


_store_service_instance: Optional["StoreService"] = None


def get_store_service() -> StoreService:
    """Get singleton StoreService instance."""
    global _store_service_instance
    if _store_service_instance is None:
        _store_service_instance = StoreService()
    return _store_service_instance
