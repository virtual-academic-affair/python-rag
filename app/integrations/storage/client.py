"""
R2 Storage Implementation.
Provides async interface to Cloudflare R2 object storage (S3-compatible).
"""

import asyncio
import io
from typing import BinaryIO, Optional
import boto3
from botocore.exceptions import ClientError
from botocore.config import Config

from app.core.config import settings
from app.core.exceptions import (
    StorageException,
    FileNotFoundInStorageException,
    FileUploadException,
    FileDownloadException,
)
from app.integrations.storage.base import BaseStorage

import logging
logger = logging.getLogger(__name__)

class R2Storage(BaseStorage):
    """
    R2 storage client (Singleton).
    Provides async operations for R2 object storage.
    """
    
    _instance: Optional["R2Storage"] = None
    _client = None
    _bucket_ensured: bool = False
    
    def __new__(cls):
        """Singleton pattern implementation."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        """Initialize R2 client (only once)."""
        if self._client is None:
            self.disabled = settings.R2_DISABLED
            if self.disabled:
                logger.warning("R2 storage is disabled.")
                self._client = None
                return

            try:
                self._client = boto3.client(
                    's3',
                    endpoint_url=settings.R2_ENDPOINT,
                    aws_access_key_id=settings.R2_ACCESS_KEY,
                    aws_secret_access_key=settings.R2_SECRET_KEY,
                    region_name=settings.R2_REGION,
                    config=Config(signature_version='s3v4')
                )
                logger.info("✅ R2 client setup (boto3)")
            except Exception as e:
                logger.error(f"❌ Failed to initialize R2 client: {e}")
                if settings.R2_BYPASS_ON_INIT_ERROR:
                    logger.warning("R2 bypass enabled. Continue startup with R2 disabled.")
                    self.disabled = True
                    self._client = None
                    return
                raise StorageException(f"R2 initialization failed: {e}")

    def get_client(self):
        """Get R2 client instance."""
        if self._client is None:
            raise RuntimeError("R2 client not initialized")
        return self._client

    async def _ensure_bucket(self):
        """Ensure bucket exists, create if not."""
        if self.disabled or self._bucket_ensured:
            return
            
        def _check_and_create():
            try:
                self._client.head_bucket(Bucket=settings.R2_BUCKET_NAME)
                self._bucket_ensured = True
            except ClientError as e:
                error_code = e.response.get('Error', {}).get('Code')
                if error_code == '404':
                    self._client.create_bucket(Bucket=settings.R2_BUCKET_NAME)
                    logger.info(f"✅ Created R2 bucket: {settings.R2_BUCKET_NAME}")
                    self._bucket_ensured = True
                else:
                    logger.error(f"Error checking/creating bucket: {e}")
                    raise StorageException(f"R2 initialization failed: {e}")

        await asyncio.to_thread(_check_and_create)

    async def upload_file(
        self,
        file: BinaryIO,
        object_name: str,
        content_type: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> dict:
        if self.disabled:
            return {}
            
        await self._ensure_bucket()
        
        try:
            # File size calculation using file seek
            file.seek(0, 2)  # Seek to end
            file_size = file.tell()
            file.seek(0)  # Reset to beginning
            
            def _upload():
                response = self._client.put_object(
                    Bucket=settings.R2_BUCKET_NAME,
                    Key=object_name,
                    Body=file,
                    ContentType=content_type or "application/octet-stream"
                )
                return response
            
            result = await asyncio.to_thread(_upload)
            
            logger.info(f"✅ Uploaded to R2: {object_name} ({file_size} bytes)")
            
            return {
                "object_name": object_name,
                "bucket": settings.R2_BUCKET_NAME,
                "etag": result.get('ETag', '').strip('"'),
                "size": file_size,
            }

        except Exception as e:
            logger.error(f"❌ Failed to upload {object_name}: {e}")
            raise FileUploadException(f"Failed to upload file to R2: {e}")

    async def download_file(self, object_name: str) -> io.BytesIO:
        if self.disabled:
            raise FileDownloadException("R2 storage disabled")
            
        try:
            def _download():
                response = self._client.get_object(
                    Bucket=settings.R2_BUCKET_NAME,
                    Key=object_name
                )
                return response['Body'].read()
                
            data = await asyncio.to_thread(_download)
            return io.BytesIO(data)
            
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code')
            if error_code == 'NoSuchKey':
                raise FileNotFoundInStorageException(f"File not found: {object_name}")
            logger.error(f"Failed to download {object_name}: {e}")
            raise FileDownloadException(f"Failed to download from R2: {e}")
            
    async def delete_file(self, object_name: str) -> bool:
        if self.disabled:
            return False
            
        try:
            def _delete():
                self._client.delete_object(
                    Bucket=settings.R2_BUCKET_NAME,
                    Key=object_name
                )
            await asyncio.to_thread(_delete)
            logger.info(f"🗑️ Deleted from R2: {object_name}")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to delete {object_name}: {e}")
            return False
            
    async def file_exists(self, object_name: str) -> bool:
        if self.disabled:
            return False
            
        try:
            def _head():
                self._client.head_object(
                    Bucket=settings.R2_BUCKET_NAME,
                    Key=object_name
                )
            await asyncio.to_thread(_head)
            return True
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code')
            if error_code == '404':
                return False
            logger.error(f"Error checking file existence {object_name}: {e}")
            return False
            
    async def get_file_url(self, object_name: str, expires: int = 3600) -> str:
        if self.disabled:
            return ""
            
        if settings.R2_PUBLIC_DOMAIN:
            domain = settings.R2_PUBLIC_DOMAIN.rstrip('/')
            return f"{domain}/{object_name}"
            
        try:
            def _presign():
                return self._client.generate_presigned_url(
                    'get_object',
                    Params={
                        'Bucket': settings.R2_BUCKET_NAME,
                        'Key': object_name
                    },
                    ExpiresIn=expires
                )
            return await asyncio.to_thread(_presign)
        except Exception as e:
            logger.error(f"❌ Failed to generate URL for {object_name}: {e}")
            return ""

    async def list_files(self, prefix: str = "") -> list[dict]:
        if self.disabled:
            return []
            
        await self._ensure_bucket()
        try:
            def _list():
                response = self._client.list_objects_v2(
                    Bucket=settings.R2_BUCKET_NAME,
                    Prefix=prefix
                )
                return response.get('Contents', [])
            
            objects = await asyncio.to_thread(_list)
            
            files = []
            for obj in objects:
                files.append({
                    "object_name": obj['Key'],
                    "size": obj['Size'],
                    "last_modified": obj['LastModified'].isoformat(),
                    "etag": obj['ETag'].strip('"')
                })
            return files
            
        except Exception as e:
            logger.error(f"❌ Failed to list files (prefix: {prefix}): {e}")
            return []

r2_storage = R2Storage()
