from __future__ import annotations
import re
import unicodedata
from dataclasses import dataclass

AXIS_DOCUMENT_TYPES = "axis:document_types"
AXIS_ENROLLMENT_YEARS = "axis:enrollment_years"
AXIS_ACADEMIC_YEARS = "axis:academic_years"

@dataclass
class NodeSpec:
    node_key: str
    node_type: str
    title: str
    summary: str
    metadata_filter: dict
    axis_key: str

def slugify_topic(title: str) -> str:
    s = unicodedata.normalize("NFD", title.strip().lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = s.replace("đ", "d")
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s

def _is_all_years(yr: dict | None) -> bool:
    if not yr:
        return True
    lo, hi = yr.get("from_year"), yr.get("to_year")
    return lo in (None, 0) and hi in (None, 9999)

def _year_key(prefix: str, yr: dict) -> str:
    lo = yr.get("from_year")
    hi = yr.get("to_year")
    # Treat missing keys as open-ended sentinels (same as _is_all_years)
    if lo is None:
        lo = 0
    if hi is None:
        hi = 9999
    return f"{prefix}:{lo}" if lo == hi else f"{prefix}:{lo}-{hi}"

def metadata_node_specs(metadata: dict) -> list[NodeSpec]:
    specs: list[NodeSpec] = []
    if metadata.get("type"):
        t = metadata["type"]
        specs.append(NodeSpec(f"type:{t}", "metadata", f"Loại văn bản: {t}",
                              f"Các tài liệu loại {t}.", {"type": t}, AXIS_DOCUMENT_TYPES))
    ey = metadata.get("enrollment_year")
    if not _is_all_years(ey):
        key = _year_key("enrollment_year", ey)
        specs.append(NodeSpec(key, "metadata", f"Khóa tuyển sinh {key.split(':',1)[1]}",
                              f"Tài liệu áp dụng cho {key.split(':',1)[1]}.",
                              {"enrollment_year": ey}, AXIS_ENROLLMENT_YEARS))
    ay = metadata.get("academic_year")
    if not _is_all_years(ay):
        key = _year_key("academic_year", ay)
        specs.append(NodeSpec(key, "metadata", f"Năm học {key.split(':',1)[1]}",
                              f"Tài liệu cho năm học {key.split(':',1)[1]}.",
                              {"academic_year": ay}, AXIS_ACADEMIC_YEARS))
    return specs
