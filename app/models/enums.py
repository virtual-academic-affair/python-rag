"""
Enums for the application.
Provides type-safe constants for status values and types.
"""

from enum import Enum


class FileStatus(str, Enum):
    """
    File processing status.
    Maps to Gemini Document State where applicable.
    """
    UPLOADING = "uploading"     # Being uploaded to R2
    PROCESSING = "processing"   # Being processed by Gemini (STATE_PENDING)
    ACTIVE = "active"           # Ready for search (STATE_ACTIVE)
    FAILED = "failed"           # Processing failed (STATE_FAILED)
