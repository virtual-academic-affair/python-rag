from __future__ import annotations

from dataclasses import dataclass, field

from app.modules.corpus.contracts import FileCandidate, FaqCandidate, TopicSelection
from app.modules.corpus.models.corpus_node import CorpusNodeDocument


@dataclass(frozen=True)
class EligibleNodeCounts:
    direct_file_count: int = 0
    direct_faq_count: int = 0
    subtree_file_count: int = 0
    subtree_faq_count: int = 0

    @property
    def total_subtree_count(self) -> int:
        return self.subtree_file_count + self.subtree_faq_count


@dataclass
class FilteredCorpusSnapshot:
    node_map: dict[str, CorpusNodeDocument]
    counts_by_key: dict[str, EligibleNodeCounts]
    visible_node_keys: set[str]
    visible_child_keys_by_parent: dict[str, list[str]]
    visible_root_keys: list[str]
    allowed_file_ids: set[str]
    allowed_faq_ids: set[str]
    prefilter: dict[str, int]
    trace_id: str = ""


@dataclass
class TraversalSession:
    snapshot: FilteredCorpusSnapshot
    roots_listed: bool = False
    revealed_node_keys: set[str] = field(default_factory=set)
    expanded_node_keys: list[str] = field(default_factory=list)
    inspected_node_keys: list[str] = field(default_factory=list)
    selected_topics: list[TopicSelection] = field(default_factory=list)
    file_candidates: list[FileCandidate] = field(default_factory=list)
    faq_candidates: list[FaqCandidate] = field(default_factory=list)
