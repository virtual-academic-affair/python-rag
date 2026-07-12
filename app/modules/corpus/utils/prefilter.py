"""
Pre-filter tất định cho corpus traversal — lọc lá theo 3 key meta chuẩn:
enrollment_year, academic_year và lecturer_only.
"""
from __future__ import annotations
from typing import Any, Optional

from app.modules.files.models.file import FileStatus
from app.modules.metadata.utils.filter_builder import get_filter_builder

PRIVILEGED_ROLES = {"admin", "lecture"}


def is_privileged(user_role: Optional[str]) -> bool:
    """admin/lecture thấy cả lá lecturer_only; mọi role khác (kể cả None) lọc như student."""
    return (user_role or "") in PRIVILEGED_ROLES


async def build_file_prefilter_query(
    metadata_filter: Optional[dict],
    user_role: Optional[str],
    lecturer_only: Optional[bool] = None,
) -> dict[str, Any]:
    query: dict[str, Any] = {"status": FileStatus.READY.value}
    if lecturer_only is not None and is_privileged(user_role):
        query["lecturer_only"] = lecturer_only
    elif not is_privileged(user_role):
        query["lecturer_only"] = {"$ne": True}
    mongo_filter = await get_filter_builder().build_mongo_filter(
        metadata_filter or {},
        mongo_prefix="custom_metadata",
    )
    query.update(mongo_filter)
    return query


async def build_faq_prefilter_query(
    metadata_filter: Optional[dict],
    user_role: Optional[str],
    lecturer_only: Optional[bool] = None,
) -> dict[str, Any]:
    query: dict[str, Any] = {"is_active": True}
    if lecturer_only is not None and is_privileged(user_role):
        query["lecturer_only"] = lecturer_only
    elif not is_privileged(user_role):
        query["lecturer_only"] = {"$ne": True}
    mongo_filter = await get_filter_builder().build_mongo_filter(
        metadata_filter or {},
        mongo_prefix="metadata_filter",
    )
    query.update(mongo_filter)
    return query
