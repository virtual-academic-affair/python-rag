from __future__ import annotations
import logging
from typing import Optional
from app.core.base_beanie_repository import BeanieRepository
from app.modules.corpus.models.corpus_node import CorpusNodeDocument, NodeType, NodeStatus

logger = logging.getLogger(__name__)


class CorpusNodeRepository(BeanieRepository[CorpusNodeDocument]):
    document_class = CorpusNodeDocument

    async def get_by_key(self, node_key: str) -> Optional[CorpusNodeDocument]:
        return await CorpusNodeDocument.find_one(CorpusNodeDocument.node_key == node_key)

    async def get_by_keys(self, keys: list[str]) -> list[CorpusNodeDocument]:
        if not keys:
            return []
        return await CorpusNodeDocument.find({"node_key": {"$in": keys}}).to_list()

    async def get_by_type(self, node_type: NodeType,
                          status: NodeStatus = NodeStatus.ACTIVE) -> list[CorpusNodeDocument]:
        return await CorpusNodeDocument.find(
            {"node_type": node_type.value, "status": status.value}
        ).to_list()

    async def get_children(self, parent_key: str) -> list[CorpusNodeDocument]:
        return await CorpusNodeDocument.find({"parent_keys": parent_key}).to_list()

    async def upsert_node(self, node_key: str, *, node_type: NodeType, title: str = "",
                          summary: str = "", metadata_filter: dict = None,
                          axis_parent_key: str = None) -> CorpusNodeDocument:
        doc = await self.get_by_key(node_key)
        if doc:
            changed = False
            if title and doc.title != title:
                doc.title = title
                changed = True
            if summary and doc.summary != summary:
                doc.summary = summary
                changed = True
            if axis_parent_key and axis_parent_key not in doc.parent_keys:
                doc.parent_keys.append(axis_parent_key)
                changed = True
            if changed:
                await doc.save()
            return doc
        doc = CorpusNodeDocument(
            node_key=node_key,
            node_type=node_type,
            title=title,
            summary=summary,
            metadata_filter=metadata_filter or {},
            parent_keys=[axis_parent_key] if axis_parent_key else [],
        )
        await doc.insert()
        if axis_parent_key:
            parent = await CorpusNodeDocument.find_one(CorpusNodeDocument.node_key == axis_parent_key)
            if parent and node_key not in parent.child_keys:
                parent.child_keys.append(node_key)
                await parent.save()
        logger.info(f"[Corpus] upsert node {node_key} ({node_type})")
        return doc

    async def add_leaf_link(self, parent_key: str, leaf_kind: str, leaf_id: str) -> None:
        field = "file_ids" if leaf_kind == "file" else "faq_ids"
        count_field = "doc_count" if leaf_kind == "file" else "faq_count"
        await CorpusNodeDocument.find_one(
            CorpusNodeDocument.node_key == parent_key
        ).update({"$addToSet": {field: leaf_id}})
        node = await self.get_by_key(parent_key)
        if node:
            real = len(node.file_ids) if leaf_kind == "file" else len(node.faq_ids)
            await node.update({"$set": {count_field: real}})
        logger.debug(f"[Corpus] link {leaf_kind}:{leaf_id} → {parent_key}")

    async def remove_leaf_link(self, parent_key: str, leaf_kind: str, leaf_id: str) -> None:
        field = "file_ids" if leaf_kind == "file" else "faq_ids"
        count_field = "doc_count" if leaf_kind == "file" else "faq_count"
        await CorpusNodeDocument.find_one(
            CorpusNodeDocument.node_key == parent_key
        ).update({"$pull": {field: leaf_id}})
        node = await self.get_by_key(parent_key)
        if node:
            real = len(node.file_ids) if leaf_kind == "file" else len(node.faq_ids)
            await node.update({"$set": {count_field: real}})
        logger.debug(f"[Corpus] unlink {leaf_kind}:{leaf_id} ✗ {parent_key}")

    async def delete_by_key(self, node_key: str) -> bool:
        doc = await self.get_by_key(node_key)
        if not doc:
            return False
        await doc.delete()
        return True
