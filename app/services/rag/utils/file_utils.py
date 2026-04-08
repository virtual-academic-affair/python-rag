"""
File utility functions.
Validation, type detection, and file handling helpers.
"""

import os
import logging
from pathlib import Path
from typing import Optional, Any
from slugify import slugify
from datetime import datetime, timezone
import re
import unicodedata
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

logger = logging.getLogger(__name__)

class UploadStep(Enum):
    """Steps in the upload process for tracking rollback."""
    VALIDATED = "validated"
    DB_CREATED = "db_created"
    R2_UPLOADED = "r2_uploaded"
    MARKDOWN_GENERATED = "markdown_generated"
    GEMINI_UPLOADED = "gemini_uploaded"
    VECTOR_DB_SAVED = "vector_db_saved"
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
    markdown_storage_path: Optional[str] = None
    gemini_document_name: Optional[str] = None
    summary: Optional[str] = None
    table_of_contents: list[str] = field(default_factory=list)
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



# ====================================
# CONSTANTS
# ====================================
# Extensions explicitly supported by Google Gemini File Search
GEMINI_SUPPORTED_EXTENSIONS = {
    '.pdf', '.docx', '.doc', '.txt', '.md', '.html', 
    '.xlsx', '.xls', '.pptx', '.csv', '.rtf'
}

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
    
    if ext not in GEMINI_SUPPORTED_EXTENSIONS:
        raise FileTypeException(ext, list(GEMINI_SUPPORTED_EXTENSIONS))


def detect_mime_type(file_path: str) -> str:
    """
    Detect MIME type of a file with prioritization for office documents.
    """
    ext = os.path.splitext(file_path)[1].lower()
    
    # 1. High-priority extension mapping (very reliable for specific types)
    mime_types = {
        '.pdf': 'application/pdf',
        '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        '.doc': 'application/msword',
        '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        '.xls': 'application/vnd.ms-excel',
        '.pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
        '.csv': 'text/csv',
        '.rtf': 'text/rtf',
        '.txt': 'text/plain',
        '.md': 'text/markdown',
        '.html': 'text/html',
    }
    
    # If it's one of our primary supported formats, trust the extension first 
    # to avoid .docx being detected as generic application/zip in production.
    if ext in mime_types:
        detected_mime = mime_types[ext]
        logger.info(f"MIME detected (extension-based): {ext} -> {detected_mime}")
        return detected_mime

    # 2. Try using filetype library for others
    if HAS_FILETYPE:
        try:
            kind = filetype.guess(file_path)
            if kind is not None:
                # If kind is zip but it's an office doc (handled above), 
                # we've already returned. For others, we trust kind.
                logger.info(f"MIME detected (filetype): {kind.mime}")
                return kind.mime
        except Exception as e:
            logger.warning(f"Filetype guess failed: {e}")
    
    # 3. Final default
    final_mime = mime_types.get(ext, 'application/octet-stream')
    logger.info(f"MIME detected (fallback): {ext} -> {final_mime}")
    return final_mime


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
    result = []
    for k, v in custom_metadata.items():
        if isinstance(v, str):
            result.append({'key': k, 'stringValue': v})
        elif isinstance(v, (int, float)):
            result.append({'key': k, 'numericValue': v})
        elif isinstance(v, list):
            # Gemini SDK expects string_list_value directly or mapped correctly based on the version
            # Using the format {'stringListValue': {'values': [str(x) for x in v]}} which is what the library serializes
            result.append({'key': k, 'stringListValue': {'values': [str(x) for x in v]}})
    return result

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

def remove_accents(input_str: str) -> str:
    """
    Remove Vietnamese accents from a string.
    Example: 'năm học' -> 'nam hoc'
    """
    if not input_str:
        return ""
    # Normalize to NFD (Decomposition)
    s = unicodedata.normalize('NFD', input_str)
    # Filter out non-spacing marks (accents)
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
    # Replace special characters like đ/Đ
    s = s.replace('đ', 'd').replace('Đ', 'D')
    return unicodedata.normalize('NFC', s)
