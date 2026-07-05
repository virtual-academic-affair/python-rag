from __future__ import annotations
import json
import logging
from typing import Optional

from google.genai import types

from app.core.config import settings
from app.integrations.llm.gemini import gemini_client
from app.modules.corpus.dtos.traversal import Candidate, TraversalResult
from app.modules.corpus.repositories.corpus_node_repository import CorpusNodeRepository
from app.modules.corpus.models.corpus_node import CorpusNodeDocument, NodeStatus, NodeType
from app.modules.corpus.traversal_logic import classify_leaf, score_candidate
from app.utils.retry import async_retry

logger = logging.getLogger(__name__)


class CorpusTraversalService:
    def __init__(self):
        self._repo: Optional[CorpusNodeRepository] = None

    @property
    def repo(self) -> CorpusNodeRepository:
        if self._repo is None:
            self._repo = CorpusNodeRepository()
        return self._repo

    async def _call_llm(self, prompt: str) -> str:
        model = settings.CORPUS_TOPIC_MODEL or settings.GEMINI_MODEL
        resp = await async_retry(
            gemini_client.client.aio.models.generate_content,
            model=model,
            contents=[prompt],
            config=types.GenerateContentConfig(
                temperature=0.0,
                response_mime_type="application/json",
            ),
        )
        return resp.text or "{}"

    async def _select_topics(
        self, question: str, topic_nodes: list[CorpusNodeDocument]
    ) -> list[str]:
        """LLM picks relevant topics from catalog. Returns list of valid node_keys."""
        if not topic_nodes:
            return []

        catalog = "\n".join(
            f"- {n.node_key}: {n.title} — {n.summary}"
            for n in topic_nodes
        )
        prompt = (
            "Bạn là trợ lý phân loại câu hỏi giáo vụ đại học.\n\n"
            f'Câu hỏi: "{question}"\n\n'
            f"Các chủ đề tài liệu:\n{catalog}\n\n"
            "Chọn các chủ đề PHÙ HỢP với câu hỏi (0 đến 5 chủ đề, có thể không chọn nào).\n"
            'Trả về JSON: {"selected_topics": ["topic:key1", "topic:key2"]}'
        )
        try:
            raw = await self._call_llm(prompt)
        except Exception as e:
            logger.warning(f"[Corpus] _select_topics LLM failed (best-effort): {e}")
            return []
        try:
            data = json.loads(raw)
            valid_keys = {n.node_key for n in topic_nodes}
            return [k for k in (data.get("selected_topics") or []) if k in valid_keys]
        except Exception:
            logger.warning(f"[Corpus] _select_topics parse error: {raw[:200]}")
            return []

    async def list_entry_nodes(self) -> list[CorpusNodeDocument]:
        """Return all active axis nodes (entry points into the graph)."""
        nodes = await self.repo.get_by_type(NodeType.AXIS)
        logger.debug(f"[Corpus] entry nodes: {[n.node_key for n in nodes]}")
        return nodes

    async def expand_nodes(self, node_keys: list[str]) -> dict[str, list[CorpusNodeDocument]]:
        """Expand each node_key to its direct children."""
        result = {}
        for key in node_keys:
            children = await self.repo.get_children(key)
            result[key] = children
        return result

    async def resolve_candidates(
        self, selected_keys: list[str], metadata_filter: dict
    ) -> TraversalResult:
        """
        Given selected node keys (metadata + topic), collect leaf nodes,
        classify by metadata_filter, apply topic bonus, and return TraversalResult.

        Topic nodes (node_type=TOPIC) have empty metadata_filter → classified "low"
        but files/faqs in topic nodes get has_topic_match=True bonus (+0.3).
        Files under BOTH a metadata node and a topic node get the full bonus.
        """
        nodes = await self.repo.get_by_keys(selected_keys)

        # Sort: metadata nodes first so their scoring takes precedence on first-seen
        nodes.sort(key=lambda n: 0 if n.node_type == NodeType.METADATA else 1)

        # Pre-collect all topic-matched file/faq IDs for bonus scoring
        topic_matched_files: set[str] = set()
        topic_matched_faqs: set[str] = set()
        for node in nodes:
            if node.node_type == NodeType.TOPIC:
                topic_matched_files.update(node.file_ids)
                topic_matched_faqs.update(node.faq_ids)

        seen_files: set[str] = set()
        seen_faqs: set[str] = set()
        file_candidates: list[Candidate] = []
        supporting_faqs: list[Candidate] = []

        for node in nodes:
            for file_id in node.file_ids:
                if file_id in seen_files:
                    continue
                seen_files.add(file_id)
                classification = classify_leaf(node.metadata_filter, metadata_filter)
                if classification == "drop":
                    continue
                has_topic = file_id in topic_matched_files
                score = score_candidate(classification, has_topic_match=has_topic)
                file_candidates.append(Candidate("file", file_id, score))

            for faq_id in node.faq_ids:
                if faq_id in seen_faqs:
                    continue
                seen_faqs.add(faq_id)
                classification = classify_leaf(node.metadata_filter, metadata_filter)
                if classification == "drop":
                    continue
                has_topic = faq_id in topic_matched_faqs
                score = score_candidate(classification, has_topic_match=has_topic)
                supporting_faqs.append(Candidate("faq", faq_id, score))

        # Secondary key on leaf_id makes ordering deterministic across calls —
        # Mongo's find() has no guaranteed order, so ties on score must not
        # depend on incidental DB return order (candidates would silently
        # flip in/out of a downstream top-N cut otherwise).
        file_candidates.sort(key=lambda c: (-c.score, c.leaf_id))
        supporting_faqs.sort(key=lambda c: (-c.score, c.leaf_id))
        logger.info(
            f"[Corpus] resolve_candidates: {len(file_candidates)} files, "
            f"{len(supporting_faqs)} faqs (filter={metadata_filter})"
        )
        return TraversalResult(file_candidates=file_candidates, supporting_faqs=supporting_faqs)

    async def _traverse_topics(self, question: str, max_depth: int = 4) -> list[str]:
        """
        Stage 2 — Corpus Traversal: duyệt lặp cây topic từ axis:topics.

        Mỗi vòng: expand_nodes lấy child topic → LLM chọn node liên quan →
        drill-down vào các node được chọn còn có topic con.
        Termination: LLM không chọn node nào, không còn node con, hoặc chạm max_depth.
        Node được chọn ở mọi tầng đều được gộp vào kết quả (gộp candidate cha + con).
        """
        frontier = ["axis:topics"]
        collected: list[str] = []

        for depth in range(max_depth):
            expanded = await self.expand_nodes(frontier)
            children: list[CorpusNodeDocument] = []
            seen: set[str] = set()
            for kids in expanded.values():
                for n in kids:
                    if (
                        n.node_type == NodeType.TOPIC
                        and n.status == NodeStatus.ACTIVE
                        and n.node_key not in seen
                    ):
                        seen.add(n.node_key)
                        children.append(n)
            if not children:
                break

            selected_keys = await self._select_topics(question, children)
            logger.info(f"[Corpus] traversal depth {depth}: selected {selected_keys}")
            if not selected_keys:
                break  # termination: không có nhánh phù hợp

            collected.extend(selected_keys)

            # Drill-down: chỉ đi tiếp vào node được chọn còn có topic con
            selected_nodes = [n for n in children if n.node_key in selected_keys]
            frontier = [
                n.node_key for n in selected_nodes
                if any(k.startswith("topic:") for k in n.child_keys)
            ]
            if not frontier:
                break

        return list(dict.fromkeys(collected))

    async def traverse(self, question: str, metadata_filter: dict) -> TraversalResult:
        """
        Stage 1: Prefilter metadata nodes by query metadata (deterministic, no LLM).
        Stage 2: Iterative topic traversal (expand_nodes + LLM drill-down).
        Then: resolve_candidates(metadata_nodes + topic_nodes, metadata_filter).
        """
        logger.info(f"[Corpus] traverse start: filter={metadata_filter}")

        # Stage 1: Metadata Resolution & Pruning (deterministic)
        metadata_nodes = await self.repo.get_by_type(NodeType.METADATA)
        selected_metadata_keys = [
            n.node_key for n in metadata_nodes
            if classify_leaf(n.metadata_filter, metadata_filter) != "drop"
        ]
        logger.info(
            f"[Corpus] prefilter: {len(selected_metadata_keys)}/{len(metadata_nodes)} metadata nodes"
        )

        # Stage 2: Corpus Traversal (iterative expand + LLM selection)
        selected_topic_keys = await self._traverse_topics(question)
        logger.info(f"[Corpus] topic selection: {selected_topic_keys}")

        all_selected = selected_metadata_keys + selected_topic_keys
        if not all_selected:
            return TraversalResult()

        return await self.resolve_candidates(all_selected, metadata_filter)


_instance: Optional[CorpusTraversalService] = None


def get_corpus_traversal_service() -> CorpusTraversalService:
    global _instance
    if _instance is None:
        _instance = CorpusTraversalService()
    return _instance
