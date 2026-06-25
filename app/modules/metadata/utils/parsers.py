"""
Metadata Parsers — Conversion from strings to structured models.
"""
from typing import Optional
from app.modules.metadata.models.value_objects import YearRange, YEAR_MIN, YEAR_MAX


def parse_year_range(value: Optional[str]) -> YearRange:
    """Parse string range formats into a YearRange object.

    Supported formats:
        '2022-2023'  → {from: 2022, to: 2023}
        '24-25'      → {from: 2024, to: 2025}
        '-2024'      → {from: 0,    to: 2024}
        '2020-'      → {from: 2020, to: 9999}
        '2022'       → {from: 2022, to: 2022}
        '24'         → {from: 2024, to: 2024}
        '' / None    → {from: 0,    to: 9999}
    """
    if not value or not str(value).strip():
        return YearRange()

    s = str(value).strip()

    def _normalize(v: str) -> Optional[int]:
        if not v:
            return None
        if not v.isdigit():
            raise ValueError(f"Invalid year format: '{v}'")
        n = int(v)
        if len(v) == 2:
            return 2000 + n
        return n

    if "-" in s:
        parts = s.split("-")
        if len(parts) != 2:
            raise ValueError(f"Invalid range format (multiple hyphens): '{s}'")
        left = parts[0].strip()
        right = parts[1].strip()

        from_year = _normalize(left) if left else YEAR_MIN
        to_year = _normalize(right) if right else YEAR_MAX
    else:
        val = _normalize(s)
        from_year = to_year = val

    # Verify order
    if from_year is not None and to_year is not None and from_year > to_year:
        raise ValueError(f"Invalid year range: from_year ({from_year}) must be <= to_year ({to_year})")

    return YearRange(
        from_year=from_year if from_year is not None else YEAR_MIN,
        to_year=to_year if to_year is not None else YEAR_MAX
    )
