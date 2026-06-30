from __future__ import annotations


def years_overlap(a: dict | None, b: dict | None) -> bool:
    if not a or not b:
        return True
    al, ah = a.get("from_year", 0), a.get("to_year", 9999)
    bl, bh = b.get("from_year", 0), b.get("to_year", 9999)
    return al <= bh and bl <= ah


_YEAR_DIMS = ("enrollment_year", "academic_year")


def classify_leaf(leaf_meta: dict, query_filter: dict) -> str:
    """keep = matches; low = leaf missing metadata for queried dim; drop = clear conflict."""
    if not query_filter:
        return "keep"
    leaf_meta = leaf_meta or {}
    saw_missing = False
    for dim in _YEAR_DIMS:
        q = query_filter.get(dim)
        if not q:
            continue
        lv = leaf_meta.get(dim)
        if not lv:
            saw_missing = True
        elif not years_overlap(lv, q):
            return "drop"
    qt = query_filter.get("type")
    if qt:
        lt = leaf_meta.get("type")
        allowed = qt if isinstance(qt, list) else [qt]
        if not lt:
            saw_missing = True
        elif lt not in allowed:
            return "drop"
    return "low" if saw_missing else "keep"


def score_candidate(classification: str, has_topic_match: bool = False) -> float:
    base = {"keep": 0.6, "low": 0.3, "drop": 0.0}.get(classification, 0.0)
    if has_topic_match:
        base += 0.3
    return round(min(base, 1.0), 3)
