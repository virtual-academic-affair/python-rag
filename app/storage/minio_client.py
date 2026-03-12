"""
MinIO Storage Implementation.
Provides async interface to MinIO object storage (S3-compatible).
"""

import asyncio
from minio import Minio
from minio.error import S3Error
from typing import BinaryIO, Optional
from io import BytesIO
import logging

from app.core.config import settings
from app.core.exceptions import (
    StorageException,
    FileNotFoundInStorageException,
    FileUploadException,
    FileDownloadException,
)
from app.storage.base import BaseStorage

logger = logging.getLogger(__name__)


class MinioStorage(BaseStorage):
    """
    MinIO storage client (Singleton).
    Provides async operations for MinIO object storage.
    """
    
    _instance: Optional["MinioStorage"] = None
    _client: Optional[Minio] = None
    _bucket_ensured: bool = False
    
    def __new__(cls):
        """Singleton pattern implementation."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        """Initialize MinIO client (only once)."""
        if self._client is None:
            try:
                self._client = Minio(
                    endpoint=settings.MINIO_ENDPOINT,
                    access_key=settings.MINIO_ACCESS_KEY,
                    secret_key=settings.MINIO_SECRET_KEY,
                    secure=settings.MINIO_USE_SSL,
                    region=settings.MINIO_REGION,
                )
                logger.info("✅ MinIO client initialized")
                # Note: Bucket will be ensured on first operation
                
            except Exception as e:
                logger.error(f"❌ Failed to initialize MinIO client: {e}")
                raise StorageException(f"MinIO initialization failed: {e}")
    
    @property
    def client(self) -> Minio:
        """Get MinIO client instance."""
        if self._client is None:
            raise RuntimeError("MinIO client not initialized")
        return self._client
    
    async def _ensure_bucket(self):
        """Ensure bucket exists, create if not."""
        if self._bucket_ensured:
            return
            
        try:
            exists = await asyncio.to_thread(
                self.client.bucket_exists,
                settings.MINIO_BUCKET_NAME
            )
            
            if not exists:
                await asyncio.to_thread(
                    self.client.make_bucket,
                    settings.MINIO_BUCKET_NAME
                )
                logger.info(f"✅ Created MinIO bucket: {settings.MINIO_BUCKET_NAME}")
            else:
                logger.info(f"MinIO bucket exists: {settings.MINIO_BUCKET_NAME}")
            
            self._bucket_ensured = True
                
        except S3Error as e:
            logger.error(f"Error ensuring bucket: {e}")
            raise StorageException(f"Failed to ensure bucket: {e}")
    
    async def upload_file(
        self,
        file: BinaryIO,
        object_name: str,
        content_type: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> dict:
        """
        Upload a file to MinIO.
        
        Args:
            file: File object (opened in binary mode)
            object_name: Object key/path (e.g., "uploads/2024/file.pdf")
            content_type: MIME type
            metadata: Additional metadata (stored as object metadata)
            
        Returns:
            dict: {
                "object_name": str,
                "bucket": str,
                "etag": str,
                "size": int
            }
        """
        # Ensure bucket exists before uploading
        await self._ensure_bucket()
        
        try:
            # Get file size
            file.seek(0, 2)  # Seek to end
            file_size = file.tell()
            file.seek(0)  # Reset to beginning
            
            # Upload to MinIO
            result = await asyncio.to_thread(
                self.client.put_object,
                bucket_name=settings.MINIO_BUCKET_NAME,
                object_name=object_name,
                data=file,
                length=file_size,
                content_type=content_type,
                metadata=metadata,
            )
            
            logger.info(f"✅ Uploaded to MinIO: {object_name} ({file_size} bytes)")
            
            return {
                "object_name": object_name,
                "bucket": settings.MINIO_BUCKET_NAME,
                "etag": result.etag,
                "size": file_size,
            }
            
        except S3Error as e:
            logger.error(f"MinIO upload error: {e}")
            raise FileUploadException(f"Failed to upload to MinIO: {e}")
        except Exception as e:
            logger.error(f"Unexpected upload error: {e}")
            raise FileUploadException(f"Upload failed: {e}")
    
    async def download_file(self, object_name: str) -> BytesIO:
        """
        Download a file from MinIO.
        
        Args:
            object_name: Object key/path
            
        Returns:
            BytesIO object with file content
        """
        try:
            response = await asyncio.to_thread(
                self.client.get_object,
                bucket_name=settings.MINIO_BUCKET_NAME,
                object_name=object_name,
            )
            
            # Read all data into BytesIO
            data = BytesIO(response.read())
            response.close()
            response.release_conn()
            
            logger.info(f"✅ Downloaded from MinIO: {object_name}")
            return data
            
        except S3Error as e:
            if e.code == "NoSuchKey":
                raise FileNotFoundInStorageException(object_name)
            logger.error(f"MinIO download error: {e}")
            raise FileDownloadException(f"Failed to download from MinIO: {e}")
        except Exception as e:
            logger.error(f"Unexpected download error: {e}")
            raise FileDownloadException(f"Download failed: {e}")
    
    async def delete_file(self, object_name: str) -> bool:
        """
        Delete a file from MinIO.
        
        Args:
            object_name: Object key/path
            
        Returns:
            True if successful
        """
        try:
            await asyncio.to_thread(
                self.client.remove_object,
                bucket_name=settings.MINIO_BUCKET_NAME,
                object_name=object_name,
            )
            
            logger.info(f"✅ Deleted from MinIO: {object_name}")
            return True
            
        except S3Error as e:
            logger.error(f"MinIO delete error: {e}")
            raise StorageException(f"Failed to delete from MinIO: {e}")
        except Exception as e:
            logger.error(f"Unexpected delete error: {e}")
            raise StorageException(f"Delete failed: {e}")
    
    async def file_exists(self, object_name: str) -> bool:
        """
        Check if file exists in MinIO.
        
        Args:
            object_name: Object key/path
            
        Returns:
            True if exists
        """
        try:
            await asyncio.to_thread(
                self.client.stat_object,
                bucket_name=settings.MINIO_BUCKET_NAME,
                object_name=object_name,
            )
            return True
            
        except S3Error as e:
            if e.code == "NoSuchKey":
                return False
            raise StorageException(f"Failed to check file existence: {e}")
    
    async def get_file_url(self, object_name: str, expires: int = 3600) -> str:
        """
        Get presigned URL for file download.
        
        Args:
            object_name: Object key/path
            expires: URL expiration in seconds (default 1 hour)
            
        Returns:
            Presigned URL string
        """
        try:
            from datetime import timedelta
            
            url = await asyncio.to_thread(
                self.client.presigned_get_object,
                bucket_name=settings.MINIO_BUCKET_NAME,
                object_name=object_name,
                expires=timedelta(seconds=expires),
            )
            
            return url
            
        except S3Error as e:
            logger.error(f"Failed to generate presigned URL: {e}")
            raise StorageException(f"Failed to generate download URL: {e}")
    
    async def list_files(self, prefix: str = "") -> list[dict]:
        """
        List files in MinIO bucket.
        
        Args:
            prefix: Filter by prefix (e.g., "uploads/2024/")
            
        Returns:
            List of file information dicts
        """
        try:
            objects = await asyncio.to_thread(
                self.client.list_objects,
                bucket_name=settings.MINIO_BUCKET_NAME,
                prefix=prefix,
                recursive=True,
            )
            
            files = []
            for obj in objects:
                files.append({
                    "object_name": obj.object_name,
                    "size": obj.size,
                    "last_modified": obj.last_modified,
                    "etag": obj.etag,
                })
            
            return files
            
        except S3Error as e:
            logger.error(f"Failed to list files: {e}")
            raise StorageException(f"Failed to list files: {e}")


# Singleton instance
minio_storage = MinioStorage()
