from __future__ import annotations
import logging
from typing import Optional
from app.core.base_beanie_repository import BeanieRepository
from app.modules.corpus.contracts import CorpusIntegrityReport
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

    async def get_nodes_containing_payload(self, payload_type: str, payload_id: str) -> list[CorpusNodeDocument]:
        """Tìm mọi node đang gắn file/faq payload này."""
        field = "direct_file_ids" if payload_type == "file" else "direct_faq_ids"
        return await CorpusNodeDocument.find({field: payload_id}).to_list()

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
        """Clear all direct/subtree payload links before a full corpus backfill."""
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

    async def validate_integrity(self) -> CorpusIntegrityReport:
        """Validate denormalized tree and aggregate invariants without mutating data."""
        nodes = await self.get_all()
        node_map = {node.node_key: node for node in nodes}
        errors: list[str] = []

        for node in nodes:
            if not set(node.direct_file_ids).issubset(node.subtree_file_ids):
                errors.append(f"{node.node_key}: direct_file_ids is not a subset of subtree_file_ids")
            if not set(node.direct_faq_ids).issubset(node.subtree_faq_ids):
                errors.append(f"{node.node_key}: direct_faq_ids is not a subset of subtree_faq_ids")
            if node.file_count != len(node.subtree_file_ids):
                errors.append(f"{node.node_key}: file_count does not match subtree_file_ids")
            if node.faq_count != len(node.subtree_faq_ids):
                errors.append(f"{node.node_key}: faq_count does not match subtree_faq_ids")
            for child_key in node.child_keys:
                child = node_map.get(child_key)
                if child is None:
                    errors.append(f"{node.node_key}: child '{child_key}' is missing")
                elif child.parent_key != node.node_key:
                    errors.append(f"{node.node_key}: child '{child_key}' has mismatched parent")
            if node.parent_key:
                parent = node_map.get(node.parent_key)
                if parent is None:
                    errors.append(f"{node.node_key}: parent '{node.parent_key}' is missing")
                elif node.node_key not in parent.child_keys:
                    errors.append(f"{node.node_key}: parent '{node.parent_key}' does not list child")

        computed: dict[str, tuple[set[str], set[str]]] = {}

        def aggregate(node_key: str, stack: set[str]) -> tuple[set[str], set[str]]:
            if node_key in computed:
                return computed[node_key]
            if node_key in stack:
                errors.append(f"{node_key}: cycle detected")
                return set(), set()
            node = node_map.get(node_key)
            if node is None:
                return set(), set()
            next_stack = stack | {node_key}
            file_ids = set(node.direct_file_ids)
            faq_ids = set(node.direct_faq_ids)
            for child_key in node.child_keys:
                child_files, child_faqs = aggregate(child_key, next_stack)
                file_ids.update(child_files)
                faq_ids.update(child_faqs)
            computed[node_key] = (file_ids, faq_ids)
            if file_ids != set(node.subtree_file_ids):
                errors.append(f"{node_key}: subtree_file_ids aggregate mismatch")
            if faq_ids != set(node.subtree_faq_ids):
                errors.append(f"{node_key}: subtree_faq_ids aggregate mismatch")
            return file_ids, faq_ids

        for node in nodes:
            aggregate(node.node_key, set())
        return CorpusIntegrityReport(valid=not errors, errors=errors)

    async def assert_integrity(self) -> None:
        report = await self.validate_integrity()
        if not report.valid:
            raise ValueError("Corpus integrity validation failed: " + "; ".join(report.errors))

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

    async def add_payload_link(self, node_key: str, payload_type: str, payload_id: str) -> bool:
        field = "direct_file_ids" if payload_type == "file" else "direct_faq_ids"
        result = await CorpusNodeDocument.find(CorpusNodeDocument.node_key == node_key).update(
            {"$addToSet": {field: payload_id}}
        )
        if getattr(result, "matched_count", None) == 0:
            return False
        await self.rebuild_node_and_ancestors(node_key)
        logger.debug(f"[Corpus] link {payload_type}:{payload_id} -> {node_key}")
        return True

    async def remove_payload_link(self, node_key: str, payload_type: str, payload_id: str) -> bool:
        field = "direct_file_ids" if payload_type == "file" else "direct_faq_ids"
        result = await CorpusNodeDocument.find(CorpusNodeDocument.node_key == node_key).update(
            {"$pull": {field: payload_id}}
        )
        if getattr(result, "matched_count", None) == 0:
            return False
        await self.rebuild_node_and_ancestors(node_key)
        logger.debug(f"[Corpus] unlink {payload_type}:{payload_id} from {node_key}")
        return True

    async def move_children(self, source_key: str, target_key: str) -> int:
        source = await self.get_by_key(source_key)
        target = await self.get_by_key(target_key)
        if not source or not target:
            return 0

        moved = 0
        for child_key in list(source.child_keys):
            child = await self.get_by_key(child_key)
            if not child:
                continue
            child.parent_key = target_key
            await child.save()
            if child_key not in target.child_keys:
                target.child_keys.append(child_key)
            moved += 1
        source.child_keys = []
        await source.save()
        await target.save()
        return moved

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
