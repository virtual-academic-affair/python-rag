"""Selection validation and candidate materialization for traversal sessions."""

from __future__ import annotations

from typing import Any

from app.core.config import settings
from app.modules.corpus.contracts import FileCandidate, FaqCandidate, TopicSelection
from app.modules.corpus.models.corpus_node import CorpusNodeDocument
from app.modules.rag.query.retrieval.traversal.contracts import (
    FilteredCorpusSnapshot,
    TraversalSession,
)


def candidate_ids(node: CorpusNodeDocument, scope: str, session: TraversalSession) -> tuple[list[str], list[str]]:
    file_ids = node.direct_file_ids if scope == "direct" else node.subtree_file_ids
    faq_ids = node.direct_faq_ids if scope == "direct" else node.subtree_faq_ids
    return (
        [file_id for file_id in file_ids if file_id in session.snapshot.allowed_file_ids],
        [faq_id for faq_id in faq_ids if faq_id in session.snapshot.allowed_faq_ids],
    )


def _is_descendant(snapshot: FilteredCorpusSnapshot, child_key: str, ancestor_key: str) -> bool:
    current = snapshot.node_map.get(child_key)
    seen: set[str] = set()
    while current and current.parent_key and current.node_key not in seen:
        seen.add(current.node_key)
        if current.parent_key == ancestor_key:
            return True
        current = snapshot.node_map.get(current.parent_key)
    return False


def select_topics(session: TraversalSession, selections: list[dict[str, Any]]) -> dict[str, Any]:
    """Validate agent selections and materialize typed candidates directly from aggregates."""
    if not isinstance(selections, list) or not selections:
        return {"status": "invalid", "reason": "selections must be a non-empty list"}
    if len(selections) > settings.CORPUS_TRAVERSAL_MAX_SELECTED_TOPICS:
        return {"status": "invalid", "reason": "too many selected topics"}

    normalized: list[TopicSelection] = []
    for raw in selections:
        if not isinstance(raw, dict):
            return {"status": "invalid", "reason": "each selection must be an object"}
        node_key = str(raw.get("node_key") or raw.get("nodeKey") or "").strip()
        scope = str(raw.get("scope") or "subtree").strip()
        if node_key not in session.revealed_node_keys or node_key not in session.snapshot.visible_node_keys:
            return {"status": "invalid", "reason": f"node_key '{node_key}' was not revealed"}
        if scope not in {"direct", "subtree"}:
            return {"status": "invalid", "reason": "scope must be direct or subtree"}
        if any(item.node_key == node_key for item in normalized):
            return {"status": "invalid", "reason": "duplicate topic selection"}
        node = session.snapshot.node_map[node_key]
        file_ids, faq_ids = candidate_ids(node, scope, session)
        if not file_ids and not faq_ids:
            return {"status": "invalid", "reason": "selection scope has no eligible payload"}
        normalized.append(TopicSelection(node_key=node_key, scope=scope, node_title=node.title))

    for item in normalized:
        for other in normalized:
            if item != other and item.scope == "subtree" and _is_descendant(session.snapshot, other.node_key, item.node_key):
                return {"status": "invalid", "reason": "subtree selection overlaps a descendant selection"}

    file_candidates: list[FileCandidate] = []
    faq_candidates: list[FaqCandidate] = []
    seen_files: set[str] = set()
    seen_faqs: set[str] = set()
    for selection in normalized:
        node = session.snapshot.node_map[selection.node_key]
        file_ids, faq_ids = candidate_ids(node, selection.scope, session)
        for file_id in file_ids:
            if file_id not in seen_files:
                seen_files.add(file_id)
                file_candidates.append(FileCandidate(file_id, node.node_key, node.title))
        for faq_id in faq_ids:
            if faq_id not in seen_faqs:
                seen_faqs.add(faq_id)
                faq_candidates.append(FaqCandidate(faq_id, node.node_key, node.title))

    has_expandable_selection = any(
        session.snapshot.visible_child_keys_by_parent.get(selection.node_key)
        for selection in normalized
    )
    if len(file_candidates) > settings.COHERE_RERANK_MAX_CANDIDATES or len(faq_candidates) > settings.COHERE_RERANK_MAX_CANDIDATES:
        return {
            "status": "requires_refinement" if has_expandable_selection else "capacity_exceeded",
            "reason": "candidate pool exceeds configured rerank capacity",
            "totalFileCandidates": len(file_candidates),
            "totalFaqCandidates": len(faq_candidates),
        }
    if has_expandable_selection and (
        len(file_candidates) > settings.CORPUS_TRAVERSAL_SOFT_FILE_LIMIT
        or len(faq_candidates) > settings.CORPUS_TRAVERSAL_SOFT_FAQ_LIMIT
    ):
        return {
            "status": "requires_refinement",
            "reason": "selected topic is broad; expand a more specific child topic",
            "totalFileCandidates": len(file_candidates),
            "totalFaqCandidates": len(faq_candidates),
        }

    session.selected_topics = normalized
    session.file_candidates = file_candidates
    session.faq_candidates = faq_candidates
    return {
        "status": "selected",
        "selectedTopics": [
            {"nodeKey": item.node_key, "nodeTitle": item.node_title, "scope": item.scope}
            for item in normalized
        ],
        "totalFileCandidates": len(file_candidates),
        "totalFaqCandidates": len(faq_candidates),
    }
