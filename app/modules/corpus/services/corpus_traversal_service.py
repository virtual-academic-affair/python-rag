from __future__ import annotations
import logging
from typing import Optional
from app.modules.corpus.dtos.traversal import Candidate, TraversalResult
from app.modules.corpus.repositories.corpus_node_repository import CorpusNodeRepository
from app.modules.corpus.models.corpus_node import CorpusNodeDocument, NodeType
from app.modules.corpus.traversal_logic import classify_leaf, score_candidate

logger = logging.getLogger(__name__)


class CorpusTraversalService:
    def __init__(self):
        self._repo: Optional[CorpusNodeRepository] = None

    @property
    def repo(self) -> CorpusNodeRepository:
        if self._repo is None:
            self._repo = CorpusNodeRepository()
        return self._repo

    async def list_entry_nodes(self) -> list[CorpusNodeDocument]:
        """Return all active axis nodes (entry points into the graph)."""
        nodes = await self.repo.get_by_type(NodeType.AXIS)
        logger.debug(f"[Corpus] entry nodes: {[n.node_key for n in nodes]}")
        return nodes

    async def expand_nodes(self, node_keys: list[str]) -> dict[str, list[CorpusNodeDocument]]:
        """Expand each node_key to its direct children. Returns {parent_key: [children]}."""
        result = {}
        for key in node_keys:
            children = await self.repo.get_children(key)
            result[key] = children
            logger.debug(f"[Corpus] expand {key}: {len(children)} children")
        return result

    async def resolve_candidates(
        self, selected_keys: list[str], metadata_filter: dict
    ) -> TraversalResult:
        """
        Given selected node keys, collect all leaf nodes (files + faqs) linked to them,
        classify each by metadata_filter, and return TraversalResult.
        """
        nodes = await self.repo.get_by_keys(selected_keys)
        seen_files: set[str] = set()
        seen_faqs: set[str] = set()
        file_candidates: list[Candidate] = []
        supporting_faqs: list[Candidate] = []

        for node in nodes:
            for file_id in node.file_ids:
                if file_id in seen_files:
                    continue
                seen_files.add(file_id)
                # Phase A: we don't load full file metadata here; use node's metadata_filter as proxy
                classification = classify_leaf(node.metadata_filter, metadata_filter)
                if classification == "drop":
                    logger.debug(f"[Corpus] drop file:{file_id} (node={node.node_key})")
                    continue
                score = score_candidate(classification)
                file_candidates.append(Candidate("file", file_id, score))
                logger.debug(f"[Corpus] candidate file:{file_id} score={score} cls={classification}")

            for faq_id in node.faq_ids:
                if faq_id in seen_faqs:
                    continue
                seen_faqs.add(faq_id)
                classification = classify_leaf(node.metadata_filter, metadata_filter)
                if classification == "drop":
                    logger.debug(f"[Corpus] drop faq:{faq_id} (node={node.node_key})")
                    continue
                score = score_candidate(classification)
                supporting_faqs.append(Candidate("faq", faq_id, score))
                logger.debug(f"[Corpus] supporting faq:{faq_id} score={score} cls={classification}")

        file_candidates.sort(key=lambda c: c.score, reverse=True)
        supporting_faqs.sort(key=lambda c: c.score, reverse=True)
        logger.info(
            f"[Corpus] resolve_candidates: {len(file_candidates)} files, "
            f"{len(supporting_faqs)} faqs (filter={metadata_filter})"
        )
        return TraversalResult(file_candidates=file_candidates, supporting_faqs=supporting_faqs)

    async def traverse(self, question: str, metadata_filter: dict) -> TraversalResult:
        """
        Phase A metadata-only traversal (no LLM, no topics).
        Collects ALL metadata nodes whose metadata_filter overlaps with query,
        then resolves leaf candidates.

        Phase B will insert an LLM topic-selection step between prefilter and resolve.
        This method is NOT wired into chat in Phase A — only used by admin router / tests.
        """
        logger.info(f"[Corpus] traverse start: filter={metadata_filter}")

        # Collect all active metadata nodes
        metadata_nodes = await self.repo.get_by_type(NodeType.METADATA)
        logger.debug(f"[Corpus] total metadata nodes: {len(metadata_nodes)}")

        # Prefilter: keep nodes whose metadata_filter overlaps with query
        selected_keys = []
        for node in metadata_nodes:
            cls = classify_leaf(node.metadata_filter, metadata_filter)
            if cls != "drop":
                selected_keys.append(node.node_key)
                logger.debug(f"[Corpus] prefilter keep: {node.node_key} (cls={cls})")

        logger.info(f"[Corpus] prefilter: {len(selected_keys)}/{len(metadata_nodes)} nodes selected")

        if not selected_keys:
            return TraversalResult()

        return await self.resolve_candidates(selected_keys, metadata_filter)


_instance: Optional[CorpusTraversalService] = None


def get_corpus_traversal_service() -> CorpusTraversalService:
    global _instance
    if _instance is None:
        _instance = CorpusTraversalService()
    return _instance
