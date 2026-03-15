"""
Base Storage Interface.
Abstract class for object storage implementations.
"""

from abc import ABC, abstractmethod
from typing import BinaryIO, Optional
from io import BytesIO


class BaseStorage(ABC):
    """Abstract base class for object storage."""
    
    @abstractmethod
    async def upload_file(
        self,
        file: BinaryIO,
        object_name: str,
        content_type: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> dict:
        """
        Upload a file to storage.
        
        Args:
            file: File object to upload
            object_name: Object key/path in storage
            content_type: MIME type
            metadata: Additional metadata
            
        Returns:
            dict with upload information (url, etag, etc.)
        """
        pass
    
    @abstractmethod
    async def download_file(self, object_name: str) -> BytesIO:
        """
        Download a file from storage.
        
        Args:
            object_name: Object key/path in storage
            
        Returns:
            BytesIO object with file content
        """
        pass
    
    @abstractmethod
    async def delete_file(self, object_name: str) -> bool:
        """
        Delete a file from storage.
        
        Args:
            object_name: Object key/path in storage
            
        Returns:
            True if successful
        """
        pass
    
    @abstractmethod
    async def file_exists(self, object_name: str) -> bool:
        """
        Check if file exists in storage.
        
        Args:
            object_name: Object key/path in storage
            
        Returns:
            True if exists
        """
        pass
    
    @abstractmethod
    async def get_file_url(self, object_name: str, expires: int = 3600) -> str:
        """
        Get presigned URL for file download.
        
        Args:
            object_name: Object key/path in storage
            expires: URL expiration in seconds
            
        Returns:
            Presigned URL
        """
        pass
    
    @abstractmethod
    async def list_files(self, prefix: str = "") -> list[dict]:
        """
        List files in storage.
        
        Args:
            prefix: Prefix filter
            
        Returns:
            List of file information dicts
        """
        pass
