from __future__ import annotations
from dataclasses import dataclass
import json
import logging
from typing import Optional
from google.genai import types
from google.genai import errors as genai_errors

from app.core.config import settings
from app.integrations.llm.gemini import gemini_client
from app.utils.retry import async_retry
from app.modules.corpus.services.corpus_service import get_corpus_service
from app.modules.corpus.utils.node_keys import slugify_topic

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TopicProposal:
    slug: str
    title: str
    summary: str = ""
    parent: Optional[str] = None


def _new_topic_limit(active_topic_count: int) -> int:
    if active_topic_count == 0:
        return 8
    if active_topic_count < 10:
        return 5
    return 3


async def call_corpus_llm(prompt: str) -> str:
    """Call Gemini LLM for topic assignment (forcing JSON response)."""
    model = settings.CORPUS_TOPIC_MODEL or settings.GEMINI_MODEL
    resp = await async_retry(
        gemini_client.client.aio.models.generate_content,
        model=model,
        contents=[prompt],
        config=types.GenerateContentConfig(
            temperature=0.0,
            response_mime_type="application/json",
        ),
        retryable_exceptions=(genai_errors.ServerError,),
    )
    return resp.text or "{}"


def _build_assignment_prompt(
    display_name: str,
    content_text: str,
    active_topics: list[tuple[str, str, str]],  # (node_key, title, summary)
) -> str:
    catalog_lines = (
        "\n".join(
            f"- {node_key}: {title} — {summary}"
            for node_key, title, summary in active_topics
        )
        if active_topics
        else "(catalog rỗng: chưa có chủ đề hiện có)"
    )
    new_topic_limit = _new_topic_limit(len(active_topics))
    selected_instruction = (
        "1. Chọn các chủ đề PHÙ HỢP từ danh sách trên (0 đến 5 chủ đề). "
        "ƯU TIÊN chủ đề con CỤ THỂ NHẤT thay vì chủ đề cha chung chung.\n"
        if active_topics
        else '1. Catalog đang rỗng, vì vậy "selected" phải là mảng rỗng [].\n'
    )
    new_topic_instruction = (
        f"2. Nếu nội dung thuộc chủ đề HOÀN TOÀN MỚI không có trong danh sách, đề xuất thêm (tối đa {new_topic_limit}). "
        'Với mỗi chủ đề mới, chọn "parent" là node_key của chủ đề cha phù hợp nhất trong danh sách trên '
        "(hoặc null nếu là nhóm chủ đề lớn hoàn toàn mới).\n\n"
        if active_topics
        else f'2. Đề xuất tối đa {new_topic_limit} chủ đề root mới phù hợp nhất. '
        'Với mỗi chủ đề mới, "parent" phải là null.\n\n'
    )

    content_snippet = content_text if content_text else "(no content)"

    return (
        "Bạn là trợ lý phân loại tài liệu giáo vụ đại học.\n\n"
        f'Tài liệu: "{display_name}"\n'
        f"Nội dung (mục lục hoặc câu hỏi/trả lời):\n{content_snippet}\n\n"
        "Chủ đề hiện có (dạng cây, chủ đề con cụ thể hơn chủ đề cha):\n"
        f"{catalog_lines}\n\n"
        "Nhiệm vụ:\n"
        f"{selected_instruction}"
        f"{new_topic_instruction}"
        "Trả về JSON:\n"
        '{"selected": ["key1"], "new_topics": [{"slug": "ten-slug-viet-khong-dau", "title": "Tên", "summary": "Mô tả ngắn", "parent": "key-cha"}]}'
    )


def _parse_assignment_response(
    raw: str,
    valid_keys: set[str],
    new_topic_limit: int,
) -> tuple[list[str], list[TopicProposal]]:
    try:
        data = json.loads(raw)
    except Exception:
        logger.warning(f"[TopicAssigner] JSON parse error: {raw[:200]}")
        return [], []

    if not isinstance(data, dict):
        logger.warning(f"[TopicAssigner] JSON root must be an object: {raw[:200]}")
        return [], []

    raw_selected = data.get("selected") or []
    selected = [
        k for k in raw_selected
        if isinstance(k, str) and k in valid_keys
    ] if isinstance(raw_selected, list) else []

    new_topics: list[TopicProposal] = []
    raw_new_topics = data.get("new_topics") or []
    if not isinstance(raw_new_topics, list):
        raw_new_topics = []
    for t in raw_new_topics:
        if not (isinstance(t, dict) and (t.get("slug") or t.get("title"))):
            continue

        raw_slug = str(t.get("slug") or "").strip()
        raw_title = str(t.get("title") or "").strip()
        raw_slug_source = raw_slug or raw_title
        normalized_slug = slugify_topic(raw_slug_source)
        if not normalized_slug:
            continue

        parent = t.get("parent")
        if not isinstance(parent, str) or parent not in valid_keys:
            parent = None
        new_topics.append(
            TopicProposal(
                slug=normalized_slug,
                title=raw_title or raw_slug_source,
                summary=str(t.get("summary") or ""),
                parent=parent,
            )
        )
        if len(new_topics) >= new_topic_limit:
            break

    return selected, new_topics


async def assign_topics(
    display_name: str,
    content_text: str,
    active_topics: list[tuple[str, str, str]],  # (node_key, title, summary)
) -> tuple[list[str], list[TopicProposal]]:
    """
    Ask LLM to assign topic node_keys to a document/FAQ.
    """
    valid_keys = {t[0] for t in active_topics}
    new_topic_limit = _new_topic_limit(len(active_topics))
    prompt = _build_assignment_prompt(display_name, content_text, active_topics)
    raw = await call_corpus_llm(prompt)
    selected, new_topics = _parse_assignment_response(raw, valid_keys, new_topic_limit)

    logger.info(
        f"[TopicAssigner] '{display_name}': selected={selected} new={[t.slug for t in new_topics]}"
    )
    return selected, new_topics


class CorpusLinker:
    """
    LLM-based topic assignment during ingestion/re-indexing of files and FAQs.
    """
    def __init__(self):
        self._corpus_service = get_corpus_service()

    async def _ensure_topic_nodes(
        self,
        display_name: str,
        content_text: str,
    ) -> list[str]:
        """
        Assign topics using LLM, auto-creating new topic nodes under their proposed parent if needed.
        """
        if not display_name and not content_text:
            logger.warning(
                "[CorpusLinker] _ensure_topic_nodes: Both display_name and content_text are empty — skipping"
            )
            return []

        all_nodes = await self._corpus_service.get_all_nodes()
        active_topics = [(n.node_key, n.title, n.summary) for n in all_nodes]

        selected_keys, new_topics = await assign_topics(
            display_name=display_name,
            content_text=content_text,
            active_topics=active_topics,
        )

        new_topic_keys = []
        for t in new_topics:
            node_key = t.slug
            # Auto-create the topic node in DB
            await self._corpus_service.repo.upsert_node(
                node_key,
                title=t.title,
                summary=t.summary,
                parent_key=t.parent,
            )
            new_topic_keys.append(node_key)
            logger.info(f"[CorpusLinker] Auto-created topic node: {node_key} (parent={t.parent})")

        if new_topic_keys:
            self._corpus_service.clear_cache()

        all_keys = selected_keys + new_topic_keys
        logger.info(f"[CorpusLinker] Final topic assignment for '{display_name[:60]}': {all_keys}")
        return all_keys

    async def index_file(
        self,
        file_id: str,
        display_name: str = "",
        doc_description: str = "",
        toc_headings: list[str] | None = None,
    ) -> list[str]:
        content_parts = []
        if doc_description:
            content_parts.append(doc_description)
        content_parts.extend(toc_headings or [])
        content_text = "\n".join(content_parts)
        topic_keys = await self._ensure_topic_nodes(display_name, content_text)
        return await self._corpus_service.reindex_leaf("file", file_id, topic_keys)

    async def index_faq(
        self,
        faq_id: str,
        question: str = "",
        answer_markdown: str = "",
    ) -> list[str]:
        content_text = f"Câu hỏi: {question}\nTrả lời: {answer_markdown}" if question else ""
        topic_keys = await self._ensure_topic_nodes(question or "", content_text)
        return await self._corpus_service.reindex_leaf("faq", faq_id, topic_keys)

    async def unindex_file(self, file_id: str) -> None:
        await self._corpus_service.unindex_file(file_id)

    async def unindex_faq(self, faq_id: str) -> None:
        await self._corpus_service.unindex_faq(faq_id)


_instance: Optional[CorpusLinker] = None


def get_corpus_linker() -> CorpusLinker:
    global _instance
    if _instance is None:
        _instance = CorpusLinker()
    return _instance
