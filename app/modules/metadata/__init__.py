"""
Metadata module public API.
"""
from app.modules.metadata.routers.metadata_router import router
from app.modules.metadata.dtos.update_metadata import YearRangeSchema

__all__ = [
    "router",
    "YearRangeSchema",
]
