"""
Base Repository Class.
Provides common CRUD operations for MongoDB collections.
"""

from typing import Optional, List, Dict, Any, TYPE_CHECKING
from bson import ObjectId
from datetime import datetime, timezone
import logging
from bson.errors import InvalidId

if TYPE_CHECKING:
    from motor.motor_asyncio import AsyncIOMotorCollection

from app.core.database import get_database
from app.core.exceptions import DatabaseException

logger = logging.getLogger(__name__)


class BaseRepository:
    """
    Base repository for MongoDB collections.
    Provides common CRUD operations with hard delete.
    """
    
    def __init__(self, collection_name: str):
        """
        Initialize repository.
        
        Args:
            collection_name: Name of the MongoDB collection
        """
        self.collection_name = collection_name
    
    @property
    def collection(self) -> Any:
        """Get collection instance."""
        db = get_database()
        return db[self.collection_name]
    
    def _to_object_id(self, id_str: str) -> ObjectId:
        """Convert string to ObjectId."""
        try:
            return ObjectId(id_str)
        except InvalidId:
            raise ValueError(f"Invalid ObjectId format: {id_str}")
    
    def _serialize_doc(self, doc: Dict[str, Any]) -> Dict[str, Any]:
        """Convert ObjectId to string in document."""
        if doc and "_id" in doc:
            doc = doc.copy()
            doc["_id"] = str(doc["_id"])
        return doc
    
    async def create(self, document: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create a new document.
        
        Args:
            document: Document data
            
        Returns:
            Created document with _id as string
        """
        try:
            document["created_at"] = datetime.now(timezone.utc)
            document["updated_at"] = datetime.now(timezone.utc)
            
            result = await self.collection.insert_one(document)
            document["_id"] = str(result.inserted_id)
            
            logger.debug(f"Created document in {self.collection_name}: {document['_id']}")
            return document
            
        except Exception as e:
            logger.error(f"Error creating document in {self.collection_name}: {e}")
            raise DatabaseException(f"Failed to create document: {e}")
    
    async def find_by_id(self, doc_id: str) -> Optional[Dict[str, Any]]:
        """
        Find document by MongoDB _id.
        
        Args:
            doc_id: Document ID (string)
            
        Returns:
            Document with _id as string, or None
        """
        try:
            document = await self.collection.find_one({"_id": self._to_object_id(doc_id)})
            return self._serialize_doc(document) if document else None
        except ValueError as e:
            logger.warning(f"Invalid ObjectId: {doc_id}")
            return None
        except Exception as e:
            logger.error(f"Error finding document in {self.collection_name}: {e}")
            raise DatabaseException(f"Failed to find document: {e}")
    
    async def find_one(self, query: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Find one document matching query.
        
        Args:
            query: MongoDB query
            
        Returns:
            Document with _id as string, or None
        """
        try:
            document = await self.collection.find_one(query)
            return self._serialize_doc(document) if document else None
        except Exception as e:
            logger.error(f"Error finding document in {self.collection_name}: {e}")
            raise DatabaseException(f"Failed to find document: {e}")
    
    async def find_many(
        self,
        query: Dict[str, Any] = None,
        skip: int = 0,
        limit: int = 20,
        sort: List[tuple] = None,
        projection: Dict[str, Any] = None,
    ) -> List[Dict[str, Any]]:
        """
        Find multiple documents.
        
        Args:
            query: MongoDB query (default: {})
            skip: Number of documents to skip
            limit: Maximum number of documents to return
            sort: Sort criteria [(field, direction), ...]
            projection: Fields to return (default: all)
            
        Returns:
            List of documents with _id as string
        """
        try:
            query = query or {}
            cursor = self.collection.find(query, projection).skip(skip).limit(limit)
            
            if sort:
                cursor = cursor.sort(sort)
            
            documents = await cursor.to_list(length=limit)
            return [self._serialize_doc(doc) for doc in documents]
            
        except Exception as e:
            logger.error(f"Error finding documents in {self.collection_name}: {e}")
            raise DatabaseException(f"Failed to find documents: {e}")
    
    async def count(self, query: Dict[str, Any] = None) -> int:
        """
        Count documents matching query.
        
        Args:
            query: MongoDB query (default: {})
            
        Returns:
            Document count
        """
        try:
            query = query or {}
            return await self.collection.count_documents(query)
        except Exception as e:
            logger.error(f"Error counting documents in {self.collection_name}: {e}")
            raise DatabaseException(f"Failed to count documents: {e}")
    
    async def update_by_id(
        self,
        doc_id: str,
        update_data: Dict[str, Any],
    ) -> bool:
        """
        Update document by _id.
        
        Args:
            doc_id: Document ID (string)
            update_data: Fields to update
            
        Returns:
            True if modified
        """
        try:
            update_data["updated_at"] = datetime.now(timezone.utc)
            
            result = await self.collection.update_one(
                {"_id": self._to_object_id(doc_id)},
                {"$set": update_data}
            )
            
            return result.modified_count > 0
            
        except ValueError as e:
            logger.warning(f"Invalid ObjectId: {doc_id}")
            return False
        except Exception as e:
            logger.error(f"Error updating document in {self.collection_name}: {e}")
            raise DatabaseException(f"Failed to update document: {e}")
    
    async def update(
        self,
        query: Dict[str, Any],
        update_data: Dict[str, Any],
    ) -> bool:
        """
        Update document matching query.
        
        Args:
            query: MongoDB query
            update_data: Fields to update
            
        Returns:
            True if modified
        """
        try:
            update_data["updated_at"] = datetime.now(timezone.utc)
            
            result = await self.collection.update_one(
                query,
                {"$set": update_data}
            )
            
            return result.modified_count > 0
            
        except Exception as e:
            logger.error(f"Error updating document in {self.collection_name}: {e}")
            raise DatabaseException(f"Failed to update document: {e}")
    
    async def delete_by_id(self, doc_id: str) -> bool:
        """
        Hard delete document by _id.
        
        Args:
            doc_id: Document ID (string)
            
        Returns:
            True if deleted
        """
        try:
            result = await self.collection.delete_one({"_id": self._to_object_id(doc_id)})
            return result.deleted_count > 0
        except ValueError as e:
            logger.warning(f"Invalid ObjectId: {doc_id}")
            return False
        except Exception as e:
            logger.error(f"Error deleting document in {self.collection_name}: {e}")
            raise DatabaseException(f"Failed to delete document: {e}")
    
    async def delete(self, query: Dict[str, Any]) -> bool:
        """
        Hard delete document matching query.
        
        Args:
            query: MongoDB query
            
        Returns:
            True if deleted
        """
        try:
            result = await self.collection.delete_one(query)
            return result.deleted_count > 0
        except Exception as e:
            logger.error(f"Error deleting document in {self.collection_name}: {e}")
            raise DatabaseException(f"Failed to delete document: {e}")
    
    async def delete_many(self, query: Dict[str, Any]) -> int:
        """
        Hard delete multiple documents.
        
        Args:
            query: MongoDB query
            
        Returns:
            Number of deleted documents
        """
        try:
            result = await self.collection.delete_many(query)
            return result.deleted_count
        except Exception as e:
            logger.error(f"Error deleting documents in {self.collection_name}: {e}")
            raise DatabaseException(f"Failed to delete documents: {e}")

    async def find_one_and_update(
        self,
        query: Dict[str, Any],
        update_data: Dict[str, Any],
        return_document: bool = True
    ) -> Optional[Dict[str, Any]]:
        """
        Find and update a document atomically.
        
        Args:
            query: MongoDB query
            update_data: Fields to update (using $set)
            return_document: If True, returns document after update
            
        Returns:
            Updated document or None
        """
        try:
            update_data["updated_at"] = datetime.now(timezone.utc)
            
            result = await self.collection.find_one_and_update(
                query,
                {"$set": update_data},
                return_document=True if return_document else False
            )
            
            return self._serialize_doc(result) if result else None
            
        except Exception as e:
            logger.error(f"Error find_one_and_update in {self.collection_name}: {e}")
            raise DatabaseException(f"Failed to update document: {e}")

    async def find_one_and_delete(self, query: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Find and delete a document atomically, returning its contents.
        
        Args:
            query: MongoDB query
            
        Returns:
            Deleted document or None
        """
        try:
            result = await self.collection.find_one_and_delete(query)
            return self._serialize_doc(result) if result else None
        except Exception as e:
            logger.error(f"Error find_one_and_delete in {self.collection_name}: {e}")
            raise DatabaseException(f"Failed to delete document: {e}")
