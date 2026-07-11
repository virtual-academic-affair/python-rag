from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class EmailQueryAnalysis:
    question: str | None
    inquiry_types: list[str]
    metadata_filter: dict[str, Any]
