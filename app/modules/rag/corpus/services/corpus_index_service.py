from __future__ import annotations
import logging
from typing import Optional

from google.genai import types

from app.core.config import settings
from app.integrations.llm.gemini import gemini_client
from app.modules.rag.corpus.repositories.corpus_node_repository import CorpusNodeRepository
from app.modules.rag.corpus.utils.topic_assigner import assign_topics
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

    async def _ensure_topic_nodes(
        self,
        display_name: str,
        content_text: str,
    ) -> list[str]:
        """
        Load topic catalog, call assign_topics LLM helper, create any new topic
        nodes (nested under their proposed parent), return selected + new keys.
        Returns [] if both display_name and content_text are empty (no LLM call).
        """
        if not display_name and not content_text:
            logger.warning(
                "[Corpus] _ensure_topic_nodes: display_name và content_text đều rỗng — bỏ qua, không gọi LLM"
            )
            return []

        topic_nodes = await self.repo.get_all()
        active_topics = [(n.node_key, n.title, n.summary) for n in topic_nodes]

        selected_keys, new_topics = await assign_topics(
            display_name=display_name,
            content_text=content_text,
            active_topics=active_topics,
            call_llm=self._call_llm,
        )

        new_topic_keys = []
        for t in new_topics:
            node_key = t["slug"]
            # LLM đề xuất cha trong cây; parent=None → topic gốc
            await self.repo.upsert_node(
                node_key,
                title=t["title"],
                summary=t.get("summary", ""),
                parent_key=t.get("parent"),
            )
            new_topic_keys.append(node_key)
            logger.info(f"[Corpus] auto-created topic node: {node_key} (parent={t.get('parent')})")

        all_keys = selected_keys + new_topic_keys
        logger.info(f"[Corpus] topic assignment for '{display_name[:60]}': {all_keys}")
        return all_keys

    async def _reindex_leaf(self, leaf_kind: str, leaf_id: str, topic_keys: list[str]) -> list[str]:
        """Sync leaf membership: file/faq là payload trên topic, diff old→new."""
        current = await self.repo.get_topics_containing_leaf(leaf_kind, leaf_id)
        old_keys = [n.node_key for n in current]
        add, remove = diff_links(old_keys, topic_keys)

        for tk in add:
            await self.repo.add_leaf_link(tk, leaf_kind, leaf_id)
        for tk in remove:
            await self.repo.remove_leaf_link(tk, leaf_kind, leaf_id)
        logger.info(f"[Corpus] index {leaf_kind}:{leaf_id}: +{add} -{remove}")
        return topic_keys

    async def index_file(
        self,
        file_id: str,
        display_name: str = "",
        toc_headings: list[str] | None = None,
    ) -> list[str]:
        content_text = "\n".join(toc_headings or [])
        topic_keys = await self._ensure_topic_nodes(display_name, content_text)
        return await self._reindex_leaf("file", file_id, topic_keys)

    async def index_faq(
        self,
        faq_id: str,
        question: str = "",
        answer_markdown: str = "",
    ) -> list[str]:
        content_text = f"Câu hỏi: {question}\nTrả lời: {answer_markdown}" if question else ""
        topic_keys = await self._ensure_topic_nodes(question or "", content_text)
        return await self._reindex_leaf("faq", faq_id, topic_keys)

    async def _unindex(self, leaf_kind: str, leaf_id: str) -> None:
        topics = await self.repo.get_topics_containing_leaf(leaf_kind, leaf_id)
        for node in topics:
            await self.repo.remove_leaf_link(node.node_key, leaf_kind, leaf_id)
        logger.info(f"[Corpus] unindex {leaf_kind}:{leaf_id} (removed from {len(topics)} topics)")

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
