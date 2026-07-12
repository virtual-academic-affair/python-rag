from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ChatQueryAnalysis:
    needs_rag: bool
    effective_question: str
    metadata_filter: dict[str, Any] | None = None
    usage: dict[str, Any] | None = None


@dataclass
class EmailQueryAnalysis:
    question: str | None
    inquiry_types: list[str]
    metadata_filter: dict[str, Any]
