"""
Metadata Parsers — Conversion from strings to structured models.
"""
from typing import Optional
from app.modules.metadata.models import YearRange, YEAR_MIN, YEAR_MAX


def parse_year_range(value: Optional[str]) -> YearRange:
    """Parse string range formats into a YearRange object.

    Supported formats:
        '2022-2023'  → {from: 2022, to: 2023}
        '-2024'      → {from: 0,    to: 2024}
        '2020-'      → {from: 2020, to: 9999}
        '2022'       → {from: 2022, to: 9999}
        '' / None    → {from: 0,    to: 9999}
    """
    if not value:
        return YearRange()

    s = str(value).strip()

    # Detect separator '-'
    if "-" in s:
        parts = s.split("-", 1)
        left = parts[0].strip()
        right = parts[1].strip()

        from_year = int(left) if left else YEAR_MIN
        to_year = int(right) if right else YEAR_MAX
        return YearRange(from_year=from_year, to_year=to_year)

    # Single number → treat as from_year with open upper bound
    try:
        return YearRange(from_year=int(s), to_year=YEAR_MAX)
    except ValueError:
        return YearRange()
