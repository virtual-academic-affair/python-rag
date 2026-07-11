from __future__ import annotations
import logging
from typing import Callable, Optional
from app.modules.corpus.repositories.corpus_node_repository import CorpusNodeRepository
from app.modules.corpus.models.corpus_node import CorpusNodeDocument

logger = logging.getLogger(__name__)


def build_traversal_tools(
    repo: CorpusNodeRepository,
    allowed_files: set[str],
    allowed_faqs: set[str],
) -> list[Callable]:
    """
    Build bound tools for the corpus traversal agent.
    Pre-filters nodes so only subtrees with allowed content are presented to the agent.
    """
    # We will fetch all nodes once to construct parent-child maps and content flags
    _all_nodes: list[CorpusNodeDocument] = []
    _node_map: dict[str, CorpusNodeDocument] = {}
    _has_content: dict[str, bool] = {}
    _counts: dict[str, tuple[int, int]] = {}
    _descendant_title_cache: dict[str, list[str]] = {}
    _expand_stack: list[str] = []

    async def _lazy_init():
        nonlocal _all_nodes, _node_map, _has_content, _counts, _descendant_title_cache
        if _all_nodes:
            return
        _all_nodes = await repo.get_all()
        _node_map = {n.node_key: n for n in _all_nodes}

        def _count_allowed(node: CorpusNodeDocument) -> tuple[int, int]:
            direct_count = (
                sum(1 for fid in node.direct_file_ids if fid in allowed_files)
                + sum(1 for qid in node.direct_faq_ids if qid in allowed_faqs)
            )
            subtree_count = (
                sum(1 for fid in node.subtree_file_ids if fid in allowed_files)
                + sum(1 for qid in node.subtree_faq_ids if qid in allowed_faqs)
            )
            return direct_count, subtree_count

        _has_content = {
            n.node_key: False for n in _all_nodes
        }
        _counts = {}
        for node in _all_nodes:
            direct_count, subtree_count = _count_allowed(node)
            _counts[node.node_key] = (direct_count, subtree_count)
            _has_content[node.node_key] = subtree_count > 0
        _descendant_title_cache = {}

    def _descendant_titles(key: str, seen: set[str]) -> list[str]:
        cached = _descendant_title_cache.get(key)
        if cached is not None:
            return cached
        titles: list[str] = []
        node = _node_map.get(key)
        if not node:
            return titles
        for ck in node.child_keys:
            if ck in seen:
                continue
            seen.add(ck)
            child = _node_map.get(ck)
            if child and _has_content.get(ck):
                titles.append(child.title or ck)
                titles.extend(_descendant_titles(ck, seen))
        _descendant_title_cache[key] = titles
        return titles

    def _format_node(node: CorpusNodeDocument) -> str:
        line = f"- {node.node_key}: {node.title} — {node.summary}"
        direct_count, subtree_count = _counts.get(node.node_key, (0, 0))
        if direct_count > 0:
            line += f" [{direct_count} mục trực tiếp]"
        if subtree_count > direct_count:
            line += f" [{subtree_count} tổng cả phân mục con]"
        kids = _descendant_titles(node.node_key, {node.node_key})
        if kids:
            line += f" (chủ đề con có tài liệu: {', '.join(kids[:12])})"
        else:
            line += " (không có chủ đề con)"
        return line

    async def list_root_topics() -> str:
        """
        List all top-level (root) topic folders that contain documents. Call this first.
        """
        await _lazy_init()
        roots = [
            n for n in _all_nodes
            if n.parent_key is None and _has_content.get(n.node_key)
        ]
        if not roots:
            return "Không tìm thấy chủ đề gốc nào có chứa tài liệu phù hợp."
        return "Danh sách các chủ đề gốc ở tầng 1:\n" + "\n".join(_format_node(n) for n in roots)

    async def expand_topic(node_key: str) -> str:
        """
        Expand a specific topic to view its sub-topics.
        Args:
            node_key: The unique slug key of the topic to expand (e.g. 'tot-nghiep').
        """
        await _lazy_init()
        node = _node_map.get(node_key)
        if not node:
            return f"Không tìm thấy chủ đề với node_key: {node_key}"
        if node_key not in _expand_stack:
            _expand_stack.append(node_key)
        children = [
            _node_map[ck] for ck in node.child_keys
            if ck in _node_map and _has_content.get(ck)
        ]
        if not children:
            return f"Chủ đề '{node.title}' ({node_key}) không có chủ đề con nào chứa tài liệu phù hợp."
        return (
            f"Danh sách chủ đề con của '{node.title}':\n"
            + "\n".join(_format_node(n) for n in children)
        )

    async def select_topics(node_keys: list[str]) -> dict:
        """
        Finalize selection: select all relevant topics that contain the files or FAQs needed. Calling this ends the traversal.
        Args:
            node_keys: List of topic node_keys selected as containing relevant documents.
        """
        await _lazy_init()
        if not isinstance(node_keys, list):
            return {"selected": [], "invalid": ["node_keys must be a list"], "total_files": 0, "total_faqs": 0}

        selected: list[str] = []
        invalid: list[str] = []
        for key in node_keys:
            normalized_key = str(key).strip() if key is not None else ""
            if not normalized_key:
                continue
            if normalized_key not in _node_map or not _has_content.get(normalized_key):
                invalid.append(normalized_key)
                continue
            if normalized_key not in selected:
                selected.append(normalized_key)

        selected_files = {
            fid
            for key in selected
            for fid in _node_map[key].subtree_file_ids
            if fid in allowed_files
        }
        selected_faqs = {
            qid
            for key in selected
            for qid in _node_map[key].subtree_faq_ids
            if qid in allowed_faqs
        }

        return {
            "selected": selected,
            "invalid": invalid,
            "expand_stack": list(_expand_stack),
            "total_files": len(selected_files),
            "total_faqs": len(selected_faqs),
        }

    # We attach the closure attributes so they can be read by loop.py if needed
    list_root_topics._lazy_init = _lazy_init
    list_root_topics._get_has_content = lambda: _has_content
    list_root_topics._get_node_map = lambda: _node_map
    list_root_topics._get_expand_stack = lambda: list(_expand_stack)

    return [list_root_topics, expand_topic, select_topics]
