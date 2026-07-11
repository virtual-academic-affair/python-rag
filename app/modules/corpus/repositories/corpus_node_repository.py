from __future__ import annotations
import logging
from typing import Optional
from app.core.base_beanie_repository import BeanieRepository
from app.modules.corpus.models.corpus_node import CorpusNodeDocument

logger = logging.getLogger(__name__)


_DEFAULT_PARENT = object()


class CorpusNodeRepository(BeanieRepository[CorpusNodeDocument]):
    document_class = CorpusNodeDocument

    async def get_by_key(self, node_key: str) -> Optional[CorpusNodeDocument]:
        return await CorpusNodeDocument.find_one(CorpusNodeDocument.node_key == node_key)

    async def get_by_keys(self, keys: list[str]) -> list[CorpusNodeDocument]:
        if not keys:
            return []
        return await CorpusNodeDocument.find({"node_key": {"$in": keys}}).to_list()

    async def get_all(self) -> list[CorpusNodeDocument]:
        return await CorpusNodeDocument.find_all().to_list()

    async def get_top_level(self) -> list[CorpusNodeDocument]:
        """Topic gốc của cây — không có cha."""
        return await CorpusNodeDocument.find({"parent_key": None}).to_list()

    async def get_children(self, parent_key: str) -> list[CorpusNodeDocument]:
        return await CorpusNodeDocument.find({"parent_key": parent_key}).to_list()

    async def get_topics_containing_leaf(self, leaf_kind: str, leaf_id: str) -> list[CorpusNodeDocument]:
        """Tìm mọi topic đang chứa file/faq này (reverse lookup cho reindex/unindex)."""
        field = "direct_file_ids" if leaf_kind == "file" else "direct_faq_ids"
        return await CorpusNodeDocument.find({field: leaf_id}).to_list()

    @staticmethod
    def _dedupe(values: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for value in values:
            if value not in seen:
                seen.add(value)
                result.append(value)
        return result

    async def get_ancestor_keys(self, node_key: str) -> list[str]:
        """Return ancestor keys from parent to root."""
        node = await self.get_by_key(node_key)
        current = node.parent_key if node else None
        ancestors: list[str] = []
        seen = {node_key}
        while current:
            if current in seen:
                logger.warning("[Corpus] cycle detected while walking ancestors from %s", node_key)
                break
            seen.add(current)
            ancestors.append(current)
            parent = await self.get_by_key(current)
            current = parent.parent_key if parent else None
        return ancestors

    async def rebuild_aggregate(self, node_key: str, seen: Optional[set[str]] = None) -> tuple[list[str], list[str]]:
        """
        Recompute subtree_file_ids/subtree_faq_ids for one node from direct links
        plus all children. Returns the computed aggregate.
        """
        seen = seen or set()
        if node_key in seen:
            logger.warning("[Corpus] cycle detected while rebuilding aggregate at %s", node_key)
            return [], []
        seen.add(node_key)

        node = await self.get_by_key(node_key)
        if not node:
            return [], []

        file_ids = list(node.direct_file_ids or [])
        faq_ids = list(node.direct_faq_ids or [])
        for child_key in list(node.child_keys or []):
            child_files, child_faqs = await self.rebuild_aggregate(child_key, seen.copy())
            file_ids.extend(child_files)
            faq_ids.extend(child_faqs)

        file_ids = self._dedupe(file_ids)
        faq_ids = self._dedupe(faq_ids)
        changed = (
            node.subtree_file_ids != file_ids
            or node.subtree_faq_ids != faq_ids
            or node.file_count != len(file_ids)
            or node.faq_count != len(faq_ids)
        )
        if changed:
            node.subtree_file_ids = file_ids
            node.subtree_faq_ids = faq_ids
            node.file_count = len(file_ids)
            node.faq_count = len(faq_ids)
            await node.save()
        return file_ids, faq_ids

    async def rebuild_node_and_ancestors(self, node_key: str) -> None:
        await self.rebuild_aggregate(node_key)
        for ancestor_key in await self.get_ancestor_keys(node_key):
            await self.rebuild_aggregate(ancestor_key)

    async def rebuild_all_aggregates(self) -> None:
        roots = await self.get_top_level()
        for root in roots:
            await self.rebuild_aggregate(root.node_key)

    async def reset_all_links(self) -> None:
        """Clear all direct/subtree leaf links before a full corpus backfill."""
        await CorpusNodeDocument.find_all().update({
            "$set": {
                "direct_file_ids": [],
                "direct_faq_ids": [],
                "subtree_file_ids": [],
                "subtree_faq_ids": [],
                "file_count": 0,
                "faq_count": 0,
            }
        })

    async def _unlink_from_parent(self, node_key: str, parent_key: Optional[str]) -> None:
        if not parent_key:
            return
        await CorpusNodeDocument.find(
            CorpusNodeDocument.node_key == parent_key
        ).update({"$pull": {"child_keys": node_key}})

    async def _link_to_parent(self, node_key: str, parent_key: Optional[str]) -> None:
        if not parent_key:
            return
        await CorpusNodeDocument.find(
            CorpusNodeDocument.node_key == parent_key
        ).update({"$addToSet": {"child_keys": node_key}})

    async def upsert_node(
        self,
        node_key: str,
        *,
        title: str = "",
        summary: str = "",
        parent_key: Optional[str] = _DEFAULT_PARENT
    ) -> CorpusNodeDocument:
        doc = await self.get_by_key(node_key)
        if doc:
            changed = False
            old_parent_key = doc.parent_key
            if title and doc.title != title:
                doc.title = title
                changed = True
            if summary and doc.summary != summary:
                doc.summary = summary
                changed = True
            if parent_key is not _DEFAULT_PARENT and doc.parent_key != parent_key:
                # Check cycle
                if await would_create_cycle(self, node_key, parent_key):
                    raise ValueError(f"Setting parent '{parent_key}' for node '{node_key}' would create a cycle.")
                # Move: gỡ khỏi cha cũ, gắn vào cha mới
                await self._unlink_from_parent(node_key, doc.parent_key)
                await self._link_to_parent(node_key, parent_key)
                doc.parent_key = parent_key
                changed = True
            if changed:
                await doc.save()
                if parent_key is not _DEFAULT_PARENT and old_parent_key != doc.parent_key:
                    await self.rebuild_node_and_ancestors(node_key)
                    if old_parent_key:
                        await self.rebuild_node_and_ancestors(old_parent_key)
            return doc

        # Check cycle for new node if parent_key is specified
        if parent_key is not _DEFAULT_PARENT and parent_key:
            if await would_create_cycle(self, node_key, parent_key):
                raise ValueError(f"Setting parent '{parent_key}' for node '{node_key}' would create a cycle.")

        doc = CorpusNodeDocument(
            node_key=node_key,
            title=title,
            summary=summary,
            parent_key=None if parent_key is _DEFAULT_PARENT else parent_key,
        )
        await doc.insert()
        if doc.parent_key:
            await self._link_to_parent(node_key, doc.parent_key)
            await self.rebuild_node_and_ancestors(doc.parent_key)
        logger.info(f"[Corpus] upsert node {node_key} (parent={doc.parent_key})")
        return doc

    async def add_leaf_link(self, topic_key: str, leaf_kind: str, leaf_id: str) -> None:
        field = "direct_file_ids" if leaf_kind == "file" else "direct_faq_ids"
        await CorpusNodeDocument.find(CorpusNodeDocument.node_key == topic_key).update(
            {"$addToSet": {field: leaf_id}}
        )
        await self.rebuild_node_and_ancestors(topic_key)
        logger.debug(f"[Corpus] link {leaf_kind}:{leaf_id} → {topic_key}")

    async def remove_leaf_link(self, topic_key: str, leaf_kind: str, leaf_id: str) -> None:
        field = "direct_file_ids" if leaf_kind == "file" else "direct_faq_ids"
        await CorpusNodeDocument.find(CorpusNodeDocument.node_key == topic_key).update(
            {"$pull": {field: leaf_id}}
        )
        await self.rebuild_node_and_ancestors(topic_key)
        logger.debug(f"[Corpus] unlink {leaf_kind}:{leaf_id} ✗ {topic_key}")

    async def delete_by_key(self, node_key: str) -> bool:
        doc = await self.get_by_key(node_key)
        if not doc:
            return False
        old_parent = doc.parent_key
        # Gỡ khỏi cha; con của node bị xóa trở thành topic gốc
        await self._unlink_from_parent(node_key, doc.parent_key)
        for ck in doc.child_keys:
            child = await self.get_by_key(ck)
            if child and child.parent_key == node_key:
                child.parent_key = None
                await child.save()
        await doc.delete()
        if old_parent:
            await self.rebuild_node_and_ancestors(old_parent)
        return True



async def would_create_cycle(repo: CorpusNodeRepository, node_key: str, parent_key: Optional[str]) -> bool:
    if not parent_key:
        return False
    if node_key == parent_key:
        return True
    current = parent_key
    visited = set()
    while current:
        if current == node_key:
            return True
        if current in visited:
            return True
        visited.add(current)
        node = await repo.get_by_key(current)
        if not node:
            break
        current = node.parent_key
    return False
