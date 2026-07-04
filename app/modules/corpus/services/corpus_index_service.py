from __future__ import annotations
import logging
from typing import Optional

from google.genai import types

from app.core.config import settings
from app.integrations.llm.gemini import gemini_client
from app.modules.corpus.node_keys import metadata_node_specs
from app.modules.corpus.repositories.corpus_node_repository import CorpusNodeRepository
from app.modules.corpus.models.corpus_node import NodeType
from app.modules.corpus.topic_assigner import assign_topics
from app.utils.retry import async_retry

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

    async def _ensure_topic_nodes(
        self,
        display_name: str,
        content_text: str,
    ) -> list[str]:
        """
        Load topic catalog, call assign_topics LLM helper, create any new topic
        nodes, return combined list of selected + new topic node_keys.
        Returns [] if both display_name and content_text are empty (no LLM call).
        """
        if not display_name and not content_text:
            return []

        topic_nodes = await self.repo.get_by_type(NodeType.TOPIC)
        active_topics = [(n.node_key, n.title, n.summary) for n in topic_nodes]

        selected_keys, new_topics = await assign_topics(
            display_name=display_name,
            content_text=content_text,
            active_topics=active_topics,
            call_llm=self._call_llm,
        )

        new_topic_keys = []
        for t in new_topics:
            node_key = f"topic:{t['slug']}"
            await self.repo.upsert_node(
                node_key,
                node_type=NodeType.TOPIC,
                title=t["title"],
                summary=t.get("summary", ""),
                axis_parent_key="axis:topics",
            )
            new_topic_keys.append(node_key)
            logger.info(f"[Corpus] auto-created topic node: {node_key}")

        all_keys = selected_keys + new_topic_keys
        logger.info(f"[Corpus] topic assignment for '{display_name[:60]}': {all_keys}")
        return all_keys

    async def _reindex_leaf(self, leaf_kind: str, leaf_id: str, parent_keys: list[str]) -> list[str]:
        """Upsert leaf node + sync links to parent_keys via diff."""
        leaf_key = f"{leaf_kind}:{leaf_id}"
        leaf = await self.repo.get_by_key(leaf_key)
        old_parents = leaf.parent_keys if leaf else []
        add, remove = diff_links(old_parents, parent_keys)

        ntype = NodeType.FILE if leaf_kind == "file" else NodeType.FAQ
        await self.repo.upsert_node(leaf_key, node_type=ntype, title=leaf_id)

        # Apply diff to parent_keys (preserve non-metadata parents for topic compatibility)
        node = await self.repo.get_by_key(leaf_key)
        if node:
            merged = set(node.parent_keys)
            merged.update(add)
            merged.difference_update(remove)
            node.parent_keys = list(merged)
            await node.save()

        for pk in add:
            await self.repo.add_leaf_link(pk, leaf_kind, leaf_id)
        for pk in remove:
            await self.repo.remove_leaf_link(pk, leaf_kind, leaf_id)
        logger.info(f"[Corpus] index {leaf_key}: +{add} -{remove} (parents={parent_keys})")
        return parent_keys

    async def index_file(
        self,
        file_id: str,
        metadata: dict,
        display_name: str = "",
        toc_headings: list[str] | None = None,
    ) -> list[str]:
        metadata_keys = await self._ensure_metadata_nodes(metadata)
        content_text = "\n".join(toc_headings or [])
        topic_keys = await self._ensure_topic_nodes(display_name, content_text)
        parents = metadata_keys + topic_keys
        return await self._reindex_leaf("file", file_id, parents)

    async def index_faq(
        self,
        faq_id: str,
        metadata: dict,
        question: str = "",
        answer_markdown: str = "",
    ) -> list[str]:
        metadata_keys = await self._ensure_metadata_nodes(metadata)
        content_text = f"Câu hỏi: {question}\nTrả lời: {answer_markdown}" if question else ""
        topic_keys = await self._ensure_topic_nodes(question or "", content_text)
        parents = metadata_keys + topic_keys
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
