from __future__ import annotations
import logging
from typing import Optional
from app.modules.corpus.node_keys import metadata_node_specs
from app.modules.corpus.repositories.corpus_node_repository import CorpusNodeRepository
from app.modules.corpus.models.corpus_node import NodeType

logger = logging.getLogger(__name__)


def diff_links(old_keys: list[str], new_keys: list[str]) -> tuple[list[str], list[str]]:
    old, new = set(old_keys), set(new_keys)
    return ([k for k in new_keys if k not in old], [k for k in old_keys if k not in new])


class CorpusIndexService:
    def __init__(self):
        self._repo: Optional[CorpusNodeRepository] = None

    @property
    def repo(self) -> CorpusNodeRepository:
        if self._repo is None:
            self._repo = CorpusNodeRepository()
        return self._repo

    async def _ensure_metadata_nodes(self, metadata: dict) -> list[str]:
        """Create/ensure metadata nodes exist; return their node_keys."""
        keys = []
        for spec in metadata_node_specs(metadata or {}):
            await self.repo.upsert_node(
                spec.node_key,
                node_type=NodeType.METADATA,
                title=spec.title,
                summary=spec.summary,
                metadata_filter=spec.metadata_filter,
                axis_parent_key=spec.axis_key,
            )
            keys.append(spec.node_key)
        return keys

    async def _reindex_leaf(self, leaf_kind: str, leaf_id: str, parent_keys: list[str]) -> list[str]:
        """Upsert leaf node + sync links to parent_keys via diff."""
        leaf_key = f"{leaf_kind}:{leaf_id}"
        leaf = await self.repo.get_by_key(leaf_key)
        old_parents = leaf.parent_keys if leaf else []
        add, remove = diff_links(old_parents, parent_keys)

        ntype = NodeType.FILE if leaf_kind == "file" else NodeType.FAQ
        await self.repo.upsert_node(leaf_key, node_type=ntype, title=leaf_id)

        # sync parent_keys on leaf
        node = await self.repo.get_by_key(leaf_key)
        if node:
            node.parent_keys = parent_keys
            await node.save()

        for pk in add:
            await self.repo.add_leaf_link(pk, leaf_kind, leaf_id)
        for pk in remove:
            await self.repo.remove_leaf_link(pk, leaf_kind, leaf_id)
        logger.info(f"[Corpus] index {leaf_key}: +{add} -{remove} (parents={parent_keys})")
        return parent_keys

    async def index_file(self, file_id: str, metadata: dict) -> list[str]:
        parents = await self._ensure_metadata_nodes(metadata)
        return await self._reindex_leaf("file", file_id, parents)

    async def index_faq(self, faq_id: str, metadata: dict) -> list[str]:
        parents = await self._ensure_metadata_nodes(metadata)
        return await self._reindex_leaf("faq", faq_id, parents)

    async def _unindex(self, leaf_kind: str, leaf_id: str) -> None:
        leaf_key = f"{leaf_kind}:{leaf_id}"
        leaf = await self.repo.get_by_key(leaf_key)
        if not leaf:
            return
        for pk in leaf.parent_keys:
            await self.repo.remove_leaf_link(pk, leaf_kind, leaf_id)
        await self.repo.delete_by_key(leaf_key)
        logger.info(f"[Corpus] unindex {leaf_key}")

    async def unindex_file(self, file_id: str) -> None:
        await self._unindex("file", file_id)

    async def unindex_faq(self, faq_id: str) -> None:
        await self._unindex("faq", faq_id)


_instance: Optional[CorpusIndexService] = None


def get_corpus_index_service() -> CorpusIndexService:
    global _instance
    if _instance is None:
        _instance = CorpusIndexService()
    return _instance
