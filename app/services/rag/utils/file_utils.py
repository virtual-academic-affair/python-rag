"""
File utility functions.
Validation, type detection, and file handling helpers.
"""

import os
from pathlib import Path
from typing import Optional
from slugify import slugify
from datetime import datetime, timezone

try:
    import filetype
    HAS_FILETYPE = True
except ImportError:
    HAS_FILETYPE = False

from app.core.config import settings
from app.core.exceptions import FileSizeException, FileTypeException


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
    import uuid
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
