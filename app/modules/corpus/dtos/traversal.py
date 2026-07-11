from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Candidate:
    leaf_kind: str          # "file" or "faq"
    leaf_id: str


@dataclass
class TraversalResult:
    file_candidates: list[Candidate] = field(default_factory=list)
    supporting_faqs: list[Candidate] = field(default_factory=list)
    traversal_order: list[str] = field(default_factory=list)
    # Trace pre-filter (debug): số lá allowed trong tree
    prefilter: Optional[dict] = None
