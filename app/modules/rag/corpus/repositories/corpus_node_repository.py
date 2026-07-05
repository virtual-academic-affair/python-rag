from __future__ import annotations
import logging
from typing import Optional
from app.core.base_beanie_repository import BeanieRepository
from app.modules.rag.corpus.models.corpus_node import CorpusNodeDocument

logger = logging.getLogger(__name__)


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
        field = "file_ids" if leaf_kind == "file" else "faq_ids"
        return await CorpusNodeDocument.find({field: leaf_id}).to_list()

    async def _unlink_from_parent(self, node_key: str, parent_key: Optional[str]) -> None:
        if not parent_key:
            return
        parent = await self.get_by_key(parent_key)
        if parent and node_key in parent.child_keys:
            parent.child_keys.remove(node_key)
            await parent.save()

    async def _link_to_parent(self, node_key: str, parent_key: Optional[str]) -> None:
        if not parent_key:
            return
        parent = await self.get_by_key(parent_key)
        if parent and node_key not in parent.child_keys:
            parent.child_keys.append(node_key)
            await parent.save()

    async def upsert_node(self, node_key: str, *, title: str = "",
                          summary: str = "", parent_key: str = None) -> CorpusNodeDocument:
        doc = await self.get_by_key(node_key)
        if doc:
            changed = False
            if title and doc.title != title:
                doc.title = title
                changed = True
            if summary and doc.summary != summary:
                doc.summary = summary
                changed = True
            if parent_key and doc.parent_key != parent_key:
                # Move: gỡ khỏi cha cũ, gắn vào cha mới
                await self._unlink_from_parent(node_key, doc.parent_key)
                await self._link_to_parent(node_key, parent_key)
                doc.parent_key = parent_key
                changed = True
            if changed:
                await doc.save()
            return doc
        doc = CorpusNodeDocument(
            node_key=node_key,
            title=title,
            summary=summary,
            parent_key=parent_key,
        )
        await doc.insert()
        await self._link_to_parent(node_key, parent_key)
        logger.info(f"[Corpus] upsert node {node_key} (parent={parent_key})")
        return doc

    async def add_leaf_link(self, topic_key: str, leaf_kind: str, leaf_id: str) -> None:
        field = "file_ids" if leaf_kind == "file" else "faq_ids"
        count_field = "doc_count" if leaf_kind == "file" else "faq_count"
        await CorpusNodeDocument.find(
            CorpusNodeDocument.node_key == topic_key
        ).update({"$addToSet": {field: leaf_id}})
        node = await self.get_by_key(topic_key)
        if node:
            real = len(node.file_ids) if leaf_kind == "file" else len(node.faq_ids)
            await node.update({"$set": {count_field: real}})
        logger.debug(f"[Corpus] link {leaf_kind}:{leaf_id} → {topic_key}")

    async def remove_leaf_link(self, topic_key: str, leaf_kind: str, leaf_id: str) -> None:
        field = "file_ids" if leaf_kind == "file" else "faq_ids"
        count_field = "doc_count" if leaf_kind == "file" else "faq_count"
        await CorpusNodeDocument.find(
            CorpusNodeDocument.node_key == topic_key
        ).update({"$pull": {field: leaf_id}})
        node = await self.get_by_key(topic_key)
        if node:
            real = len(node.file_ids) if leaf_kind == "file" else len(node.faq_ids)
            await node.update({"$set": {count_field: real}})
        logger.debug(f"[Corpus] unlink {leaf_kind}:{leaf_id} ✗ {topic_key}")

    async def delete_by_key(self, node_key: str) -> bool:
        doc = await self.get_by_key(node_key)
        if not doc:
            return False
        # Gỡ khỏi cha; con của node bị xóa trở thành topic gốc
        await self._unlink_from_parent(node_key, doc.parent_key)
        for ck in doc.child_keys:
            child = await self.get_by_key(ck)
            if child and child.parent_key == node_key:
                child.parent_key = None
                await child.save()
        await doc.delete()
        return True
