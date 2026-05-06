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
import uuid
try:
    import filetype
    HAS_FILETYPE = True
except ImportError:
    HAS_FILETYPE = False

from app.core.config import settings
from app.core.exceptions import FileSizeException, FileTypeException
from app.core.text_utils import remove_accents

logger = logging.getLogger(__name__)


# ====================================
# CONSTANTS
# ====================================
SUPPORTED_EXTENSIONS = {
    '.pdf', '.docx', '.doc', '.txt', '.md', '.html', 
    '.xlsx', '.xls', '.pptx', '.csv', '.rtf'
}

def validate_file_size(file_size_bytes: int) -> None:
    max_size_bytes = settings.MAX_FILE_SIZE_MB * 1024 * 1024
    if file_size_bytes > max_size_bytes:
        size_mb = file_size_bytes / (1024 * 1024)
        raise FileSizeException(size_mb, settings.MAX_FILE_SIZE_MB)

def validate_file_extension(filename: str) -> None:
    ext = os.path.splitext(filename)[1].lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise FileTypeException(ext, list(SUPPORTED_EXTENSIONS))

def detect_mime_type(file_path: str) -> str:
    ext = os.path.splitext(file_path)[1].lower()
    mime_types = {
        '.pdf': 'application/pdf',
        '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        '.doc': 'application/msword',
        '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        '.xls': 'application/vnd.ms-excel',
        '.pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
        '.csv': 'text/csv; charset=utf-8',
        '.rtf': 'text/rtf; charset=utf-8',
        '.txt': 'text/plain; charset=utf-8',
        '.md': 'text/markdown; charset=utf-8',
        '.html': 'text/html; charset=utf-8',
    }
    if ext in mime_types:
        return mime_types[ext]
    if HAS_FILETYPE:
        try:
            kind = filetype.guess(file_path)
            if kind is not None:
                return kind.mime
        except Exception:
            pass
    return mime_types.get(ext, 'application/octet-stream')

def generate_file_id() -> str:
    return str(uuid.uuid4())

def generate_storage_path(
    filename: str,
) -> str:
    """Generate storage path for file."""
    now = datetime.now(timezone.utc)
    year = now.strftime("%Y")
    month = now.strftime("%m")
    
    name, ext = os.path.splitext(filename)
    safe_name = slugify(name)
    safe_filename = f"{safe_name}{ext}"
    
    parts = ["uploads"]
    parts.extend([year, month])
    
    timestamp = now.strftime("%Y%m%d_%H%M%S")
    unique_filename = f"{timestamp}_{safe_filename}"
    parts.append(unique_filename)
    
    return "/".join(parts)

def format_file_size(size_bytes: int) -> str:
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} PB"

def get_file_extension(filename: str) -> str:
    return os.path.splitext(filename)[1].lower()

def get_download_url(storage_path: str) -> Optional[str]:
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
