"""
Enums for the application.
Provides type-safe constants for status values and types.
"""

from enum import Enum


class FileStatus(str, Enum):
    """
    File processing status.
    Maps to async upload pipeline states.
    """
    UPLOADING = "uploading"     # Temporary state while receiving/uploading original file
    PENDING = "pending"         # Uploaded to R2, queued/running background processing
    PROCESSING = "processing"   # Backward-compatible alias status
    ACTIVE = "active"           # Ready for retrieval
    FAILED = "failed"           # Processing failed
