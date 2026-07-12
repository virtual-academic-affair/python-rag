from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Optional


CorpusRole = Literal["student", "lecture", "admin"]
TraversalStatus = Literal["selected", "no_match"]
TopicSelectionScope = Literal["direct", "subtree"]


@dataclass
class FileCandidate:
    file_id: str
    node_key: str | None = None
    node_title: str | None = None


@dataclass
class FaqCandidate:
    faq_id: str
    node_key: str | None = None
    node_title: str | None = None


@dataclass(frozen=True)
class TopicSelection:
    node_key: str
    scope: TopicSelectionScope = "subtree"
    node_title: str | None = None


@dataclass
class TraversalResult:
    status: TraversalStatus = "no_match"
    file_candidates: list[FileCandidate] = field(default_factory=list)
    faq_candidates: list[FaqCandidate] = field(default_factory=list)
    selected_topics: list[TopicSelection] = field(default_factory=list)
    traversal_node_keys: list[str] = field(default_factory=list)
    inspected_node_keys: list[str] = field(default_factory=list)
    termination_reason: str = ""
    turn_count: int = 0
    token_usage: dict[str, int] | None = None
    prefilter: Optional[dict] = None
    steps: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class CorpusIntegrityReport:
    valid: bool
    errors: list[str] = field(default_factory=list)
