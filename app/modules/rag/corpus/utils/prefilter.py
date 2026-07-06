"""
Pre-filter tất định cho corpus traversal — lọc lá theo 3 key meta chuẩn:
enrollment_year, academic_year (ràng buộc mềm, nới được) và lecturer_only
(quyền truy cập — không bao giờ nới).
"""
from __future__ import annotations
from typing import Any, Optional

from app.modules.files.models.file import FileStatus

PRIVILEGED_ROLES = {"admin", "lecture"}


def is_privileged(user_role: Optional[str]) -> bool:
    """admin/lecture thấy cả lá lecturer_only; mọi role khác (kể cả None) lọc như student."""
    return (user_role or "") in PRIVILEGED_ROLES


def has_year_filter(metadata_filter: Optional[dict]) -> bool:
    mf = metadata_filter or {}
    return bool(mf.get("enrollment_year") or mf.get("academic_year"))


def year_overlap_conditions(metadata_filter: Optional[dict], prefix: str) -> list[dict]:
    """
    Điều kiện Mongo "năm giao ∨ thiếu metadata năm" cho từng chiều năm.
    Lá không ghi năm vẫn được giữ (áp dụng chung mọi khóa — ưu tiên thấp).
    """
    conds: list[dict] = []
    for dim in ("enrollment_year", "academic_year"):
        yr = (metadata_filter or {}).get(dim)
        if not yr:
            continue
        lo = yr.get("from_year") or 0
        hi = yr.get("to_year") or 9999
        conds.append({"$or": [
            {f"{prefix}.{dim}": None},
            {
                f"{prefix}.{dim}.from_year": {"$lte": hi},
                f"{prefix}.{dim}.to_year": {"$gte": lo},
            },
        ]})
    return conds


def build_file_prefilter_query(
    metadata_filter: Optional[dict],
    user_role: Optional[str],
    relax_years: bool = False,
) -> dict[str, Any]:
    query: dict[str, Any] = {"status": FileStatus.READY.value}
    if not is_privileged(user_role):
        query["lecturer_only"] = {"$ne": True}
    if not relax_years:
        conds = year_overlap_conditions(metadata_filter, "custom_metadata")
        if conds:
            query["$and"] = conds
    return query


def build_faq_prefilter_query(
    metadata_filter: Optional[dict],
    user_role: Optional[str],
    relax_years: bool = False,
) -> dict[str, Any]:
    query: dict[str, Any] = {"is_active": True}
    if not is_privileged(user_role):
        query["lecturer_only"] = {"$ne": True}
    if not relax_years:
        conds = year_overlap_conditions(metadata_filter, "metadata_filter")
        if conds:
            query["$and"] = conds
    return query
