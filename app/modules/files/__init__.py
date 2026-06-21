"""
Files module public API.
"""
from app.modules.files.routers.file_router import router
from app.modules.files.models.file import FileDocument, FileStatus

__all__ = [
    "router",
    "FileDocument",
    "FileStatus",
]
