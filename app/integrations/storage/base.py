"""
Base Storage Interface.
Defines the contract for object storage implementations.
"""

from abc import ABC, abstractmethod
from typing import BinaryIO, Optional, List, Dict, Any
import io


class BaseStorage(ABC):
    """Abstract base class for storage implementations."""

    @abstractmethod
    async def upload_file(
        self,
        file: BinaryIO,
        object_name: str,
        content_type: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> dict:
        """Upload a file to storage."""
        pass

    @abstractmethod
    async def download_file(self, object_name: str) -> io.BytesIO:
        """Download a file from storage."""
        pass

    @abstractmethod
    async def delete_file(self, object_name: str) -> bool:
        """Delete a file from storage."""
        pass

    @abstractmethod
    async def file_exists(self, object_name: str) -> bool:
        """Check if a file exists in storage."""
        pass

    @abstractmethod
    async def get_file_url(self, object_name: str, expires: int = 3600) -> str:
        """Get a temporary or public URL for a file."""
        pass

    @abstractmethod
    async def list_files(self, prefix: str = "") -> list[dict]:
        """List files in storage."""
        pass
