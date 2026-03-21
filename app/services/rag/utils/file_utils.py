"""
File utility functions.
Validation, type detection, and file handling helpers.
"""

import os
from pathlib import Path
from typing import Optional, Any
from slugify import slugify
from datetime import datetime, timezone
import re
import uuid
try:
    import filetype
    HAS_FILETYPE = True
except ImportError:
    HAS_FILETYPE = False

from enum import Enum
from dataclasses import dataclass, field
from app.core.config import settings
from app.core.exceptions import FileSizeException, FileTypeException

class UploadStep(Enum):
    """Steps in the upload process for tracking rollback."""
    VALIDATED = "validated"
    DB_CREATED = "db_created"
    R2_UPLOADED = "r2_uploaded"
    GEMINI_UPLOADED = "gemini_uploaded"
    METADATA_SYNCED = "metadata_synced"
    COMPLETED = "completed"


@dataclass
class UploadState:
    """
    Track upload progress for intelligent rollback.
    Each step completed is recorded to enable precise cleanup on failure.
    """
    file_id: Optional[str] = None
    storage_path: Optional[str] = None
    gemini_document_name: Optional[str] = None
    custom_metadata: Optional[dict] = None
    completed_steps: list = field(default_factory=list)
    
    def mark_step(self, step: UploadStep):
        """Record a completed step."""
        self.completed_steps.append(step)
    
    def has_step(self, step: UploadStep) -> bool:
        """Check if a step was completed."""
        return step in self.completed_steps


@dataclass
class GeminiFile:
    """Result from Gemini upload."""
    name: str
    uri: Optional[str] = None



def validate_file_size(file_size_bytes: int) -> None:
    """
    Validate file size against maximum allowed.
    
    Args:
        file_size_bytes: File size in bytes
        
    Raises:
        FileSizeException: If file exceeds maximum size
    """
    max_size_bytes = settings.MAX_FILE_SIZE_MB * 1024 * 1024
    
    if file_size_bytes > max_size_bytes:
        size_mb = file_size_bytes / (1024 * 1024)
        raise FileSizeException(size_mb, settings.MAX_FILE_SIZE_MB)


def validate_file_extension(filename: str) -> None:
    """
    Validate file extension against allowed types.
    
    Args:
        filename: File name with extension
        
    Raises:
        FileTypeException: If file type not allowed
    """
    ext = os.path.splitext(filename)[1].lower()
    
    if ext not in settings.allowed_extensions_list:
        raise FileTypeException(ext, settings.allowed_extensions_list)


def detect_mime_type(file_path: str) -> str:
    """
    Detect MIME type of a file.
    
    Args:
        file_path: Path to file
        
    Returns:
        MIME type string
    """
    # Try using filetype library
    if HAS_FILETYPE:
        try:
            kind = filetype.guess(file_path)
            if kind is not None:
                return kind.mime
        except Exception:
            pass
    
    # Fallback to extension-based detection
    ext = os.path.splitext(file_path)[1].lower()
    mime_types = {
        '.pdf': 'application/pdf',
        '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        '.doc': 'application/msword',
        '.txt': 'text/plain',
        '.md': 'text/markdown',
        '.html': 'text/html',
    }
    return mime_types.get(ext, 'application/octet-stream')


def generate_file_id() -> str:
    """
    Generate unique file ID.
    
    Returns:
        UUID string
    """
    return str(uuid.uuid4())


def generate_storage_path(
    store_id: str,
    filename: str,
    organization_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> str:
    """
    Generate storage path for file.
    Structure: {store_id}/{year}/{month}/{filename}
    
    Args:
        store_id: Store ID for the file
        filename: Original filename
        organization_id: Organization ID (optional)
        user_id: User ID (optional)
        
    Returns:
        Storage path string
    """
    now = datetime.now(timezone.utc)
    year = now.strftime("%Y")
    month = now.strftime("%m")
    
    # Sanitize filename
    name, ext = os.path.splitext(filename)
    safe_name = slugify(name)
    safe_filename = f"{safe_name}{ext}"
    
    # Build path - use store_id as base directory
    parts = []
    
    # Sanitize store_id (remove 'corpora/' prefix if exists)
    safe_store_id = store_id.replace('corpora/', '').replace('fileSearchStores/', '')
    parts.append(safe_store_id)
    
    if organization_id:
        parts.append(organization_id)
    
    parts.extend([year, month])
    
    # Add timestamp to avoid collisions
    timestamp = now.strftime("%Y%m%d_%H%M%S")
    unique_filename = f"{timestamp}_{safe_filename}"
    parts.append(unique_filename)
    
    return "/".join(parts)


def format_file_size(size_bytes: int) -> str:
    """
    Format file size in human-readable format.
    
    Args:
        size_bytes: Size in bytes
        
    Returns:
        Formatted string (e.g., "2.5 MB")
    """
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} PB"


def get_file_extension(filename: str) -> str:
    """
    Get file extension (lowercase, with dot).
    
    Args:
        filename: File name
        
    Returns:
        Extension string (e.g., ".pdf")
    """
    return os.path.splitext(filename)[1].lower()

def get_download_url(storage_path: str) -> Optional[str]:
    """
    Generate direct download URL for a file.
    Returns None if R2_PUBLIC_DOMAIN is not configured.
    """
    if not settings.R2_PUBLIC_DOMAIN or not storage_path:
        return None
    
    base_url = settings.R2_PUBLIC_DOMAIN.rstrip('/')
    path = storage_path.lstrip('/')
    return f"{base_url}/{path}"

def cleanup_temp_file(file_path: str) -> None:
    try:
        if file_path and os.path.exists(file_path):
            os.unlink(file_path)
    except Exception:
        pass

def to_snake(name: str) -> str:
    """Convert camelCase string to snake_case."""
    name = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', name)
    return re.sub('([a-z0-9])([A-Z])', r'\1_\2', name).lower()

def normalize_to_snake(value: Any) -> Any:
    """
    Recursively normalize strings and list of strings to snake_case.
    Also handles dictionaries by normalizing both keys and values.
    """
    if isinstance(value, str):
        return to_snake(value)
    if isinstance(value, list):
        return [normalize_to_snake(v) for v in value]
    if isinstance(value, dict):
        return {to_snake(k): normalize_to_snake(v) for k, v in value.items()}
    return value

def convert_custom_metadata_to_snake(custom_metadata: dict) -> dict:
    """
    Convert all keys and string values in a dictionary from camelCase to snake_case.
    """
    if not custom_metadata:
        return {}
    return normalize_to_snake(custom_metadata)

def convert_metadata_for_gemini(custom_metadata: dict) -> list[dict]:
    if not custom_metadata:
        return []
    return [{'key': k, 'stringValue': v} if isinstance(v, str) else {'key': k, 'numericValue': v} if isinstance(v, (int, float)) else {'key': k, 'stringListValue': {'values': v}} for k, v in custom_metadata.items()]

def to_camel(name: str) -> str:
    """Convert snake_case string to camelCase."""
    components = name.split('_')
    if not components:
        return ""
    return components[0] + ''.join(x.title() for x in components[1:])

def convert_custom_metadata_to_camel(custom_metadata: dict) -> dict:
    """Convert all keys in a dictionary from snake_case to camelCase."""
    if not custom_metadata:
        return {}
    return {to_camel(k): v for k, v in custom_metadata.items()}
