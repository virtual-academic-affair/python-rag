from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class Candidate:
    leaf_kind: str          # "file" or "faq"
    leaf_id: str
    score: float
    title: str = ""


@dataclass
class TraversalResult:
    file_candidates: list[Candidate] = field(default_factory=list)
    supporting_faqs: list[Candidate] = field(default_factory=list)
