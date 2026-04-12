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
    VECTOR_DB_SAVED = "vector_db_saved"
    METADATA_SYNCED = "metadata_synced"
    COMPLETED = "completed"

@dataclass
class UploadState:
    """Track upload progress for intelligent rollback."""
    file_id: Optional[str] = None
    storage_path: Optional[str] = None
    markdown_storage_path: Optional[str] = None
    summary: Optional[str] = None
    table_of_contents: list[str] = field(default_factory=list)
    custom_metadata: Optional[dict] = None
    completed_steps: list = field(default_factory=list)

    def mark_step(self, step: UploadStep):
        self.completed_steps.append(step)
    
    def has_step(self, step: UploadStep) -> bool:
        return step in self.completed_steps

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
        '.csv': 'text/csv',
        '.rtf': 'text/rtf',
        '.txt': 'text/plain',
        '.md': 'text/markdown',
        '.html': 'text/html',
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

def to_snake(name: str) -> str:
    name = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', name)
    return re.sub('([a-z0-9])([A-Z])', r'\1_\2', name).lower()

def normalize_to_snake(value: Any) -> Any:
    if isinstance(value, str):
        return to_snake(value)
    if isinstance(value, list):
        return [normalize_to_snake(v) for v in value]
    if isinstance(value, dict):
        return {to_snake(k): normalize_to_snake(v) for k, v in value.items()}
    return value

def convert_custom_metadata_to_snake(custom_metadata: dict) -> dict:
    if not custom_metadata:
        return {}
    return normalize_to_snake(custom_metadata)

def to_camel(name: str) -> str:
    components = name.split('_')
    if not components:
        return ""
    return components[0] + ''.join(x.title() for x in components[1:])

def convert_custom_metadata_to_camel(custom_metadata: dict) -> dict:
    if not custom_metadata:
        return {}
    return {to_camel(k): v for k, v in custom_metadata.items()}

def remove_accents(input_str: str) -> str:
    if not input_str:
        return ""
    s = unicodedata.normalize('NFD', input_str)
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
    s = s.replace('đ', 'd').replace('Đ', 'D')
    return unicodedata.normalize('NFC', s)
