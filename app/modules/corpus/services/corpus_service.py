from __future__ import annotations
import asyncio
import logging
from typing import Optional

from app.modules.corpus.repositories.corpus_node_repository import CorpusNodeRepository
from app.modules.corpus.models.corpus_node import CorpusNodeDocument
from app.modules.corpus.dtos.traversal import Candidate, TraversalResult

logger = logging.getLogger(__name__)


def diff_links(old_keys: list[str], new_keys: list[str]) -> tuple[list[str], list[str]]:
    old, new = set(old_keys), set(new_keys)
    return ([k for k in new_keys if k not in old], [k for k in old_keys if k not in new])


class CorpusService:
    def __init__(self):
        self._repo: Optional[CorpusNodeRepository] = None
        self._all_nodes_cache: Optional[list[CorpusNodeDocument]] = None

    def clear_cache(self) -> None:
        self._all_nodes_cache = None

    @property
    def repo(self) -> CorpusNodeRepository:
        if self._repo is None:
            self._repo = CorpusNodeRepository()
        return self._repo

    async def get_all_nodes(self) -> list[CorpusNodeDocument]:
        if self._all_nodes_cache is None:
            self._all_nodes_cache = await self.repo.get_all()
        return self._all_nodes_cache

    async def fetch_allowed_ids(
        self,
        metadata_filter: Optional[dict],
        user_role: Optional[str],
    ) -> tuple[set[str], set[str]]:
        """Fetch allowed leaf IDs through domain services."""
        from app.modules.files.services.file_service import get_file_service
        from app.modules.faq.services.faq_service import get_faq_service

        file_svc = get_file_service()
        faq_svc = await get_faq_service()
        file_ids, faq_ids = await asyncio.gather(
            file_svc.find_ids_for_corpus(metadata_filter, user_role),
            faq_svc.find_ids_for_corpus(metadata_filter, user_role),
        )
        return file_ids, faq_ids

    async def resolve_candidates(
        self,
        selected_keys: list[str],
        allowed_files: Optional[set[str]] = None,
        allowed_faqs: Optional[set[str]] = None,
        traversal_order: Optional[list[str]] = None,
    ) -> TraversalResult:
        """Resolve selected topic subtrees to direct file/FAQ leaves, child nodes first."""
        all_nodes = await self.repo.get_all()
        node_map = {n.node_key: n for n in all_nodes}

        reverse_expand = list(reversed(traversal_order or []))
        expand_index = {key: idx for idx, key in enumerate(reverse_expand)}

        def depth(key: str) -> int:
            current = node_map.get(key)
            seen: set[str] = set()
            d = 0
            while current and current.parent_key and current.parent_key not in seen:
                seen.add(current.node_key)
                d += 1
                current = node_map.get(current.parent_key)
            return d

        def collect_subtree_keys(key: str, seen: set[str]) -> list[str]:
            if key in seen or key not in node_map:
                return []
            seen.add(key)
            keys = [key]
            for child_key in node_map[key].child_keys:
                keys.extend(collect_subtree_keys(child_key, seen))
            return keys

        ordered_topic_keys: list[str] = []
        seen_topic_keys: set[str] = set()
        topic_group_index: dict[str, int] = {}
        for selected_idx, selected_key in enumerate(selected_keys):
            for topic_key in collect_subtree_keys(selected_key, set()):
                if topic_key not in seen_topic_keys:
                    seen_topic_keys.add(topic_key)
                    topic_group_index[topic_key] = selected_idx
                    ordered_topic_keys.append(topic_key)

        ordered_topic_keys.sort(
            key=lambda key: (
                topic_group_index.get(key, len(topic_group_index)),
                -depth(key),
                expand_index.get(key, len(expand_index)),
                key,
            )
        )

        seen_files: set[str] = set()
        seen_faqs: set[str] = set()
        file_candidates: list[Candidate] = []
        supporting_faqs: list[Candidate] = []

        for key in ordered_topic_keys:
            node = node_map.get(key)
            if not node:
                continue
            for file_id in node.direct_file_ids:
                if allowed_files is not None and file_id not in allowed_files:
                    continue
                if file_id not in seen_files:
                    seen_files.add(file_id)
                    file_candidates.append(Candidate("file", file_id))
            for faq_id in node.direct_faq_ids:
                if allowed_faqs is not None and faq_id not in allowed_faqs:
                    continue
                if faq_id not in seen_faqs:
                    seen_faqs.add(faq_id)
                    supporting_faqs.append(Candidate("faq", faq_id))

        logger.info(
            f"[Corpus] resolve_candidates: {len(file_candidates)} files, "
            f"{len(supporting_faqs)} faqs (topics={selected_keys}, resolved={ordered_topic_keys})"
        )
        return TraversalResult(
            file_candidates=file_candidates,
            supporting_faqs=supporting_faqs,
            traversal_order=traversal_order or [],
        )

    async def reindex_leaf(self, leaf_kind: str, leaf_id: str, topic_keys: list[str]) -> list[str]:
        """Sync leaf membership: file/faq is a payload on a topic node."""
        current = await self.repo.get_topics_containing_leaf(leaf_kind, leaf_id)
        old_keys = [n.node_key for n in current]
        add, remove = diff_links(old_keys, topic_keys)

        for tk in add:
            await self.repo.add_leaf_link(tk, leaf_kind, leaf_id)
        for tk in remove:
            await self.repo.remove_leaf_link(tk, leaf_kind, leaf_id)
        logger.info(f"[Corpus] index {leaf_kind}:{leaf_id}: +{add} -{remove}")
        return topic_keys

    async def _unindex(self, leaf_kind: str, leaf_id: str) -> None:
        topics = await self.repo.get_topics_containing_leaf(leaf_kind, leaf_id)
        for node in topics:
            await self.repo.remove_leaf_link(node.node_key, leaf_kind, leaf_id)
        logger.info(f"[Corpus] unindex {leaf_kind}:{leaf_id} (removed from {len(topics)} topics)")

    async def unindex_file(self, file_id: str) -> None:
        await self._unindex("file", file_id)

    async def unindex_faq(self, faq_id: str) -> None:
        await self._unindex("faq", faq_id)


_instance: Optional[CorpusService] = None


def get_corpus_service() -> CorpusService:
    global _instance
    if _instance is None:
        _instance = CorpusService()
    return _instance
