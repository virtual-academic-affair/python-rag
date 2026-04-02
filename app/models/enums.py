"""
Enums for the application.
Provides type-safe constants for status values and types.
"""

from enum import Enum


class FileStatus(str, Enum):
    """
    File processing status.
    Provider-neutral upload/index lifecycle.
    """
    UPLOADING = "uploading"     # Being uploaded to R2
    PROCESSING = "processing"   # Being parsed/chunked/indexed
    ACTIVE = "active"           # Ready for retrieval
    FAILED = "failed"           # Processing failed
