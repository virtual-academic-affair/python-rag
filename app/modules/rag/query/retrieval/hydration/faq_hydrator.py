"""
FAQ hydration for RAG retrieval.

FAQ được hydrate để pipeline kiểm tra trả lời trực tiếp trước. Nếu không đủ khớp,
FAQ tiếp tục được nhồi vào prompt như ngữ cảnh bổ trợ cho PageIndex agent.
"""
from __future__ import annotations
import asyncio
import logging
from datetime import datetime

from pydantic import BaseModel, ConfigDict, ValidationError

from app.core.config import settings
from app.integrations.redis.client import get_redis_client
from app.modules.metadata.models.value_objects import FaqMetadata
from app.modules.rag.cache import faq_entity_key
from app.modules.faq.services.faq_service import get_faq_service

logger = logging.getLogger(__name__)


class FaqEntityCacheEntry(BaseModel):
    """FAQ fields needed by retrieval, rerank, answering, and inspection."""

    model_config = ConfigDict(extra="forbid")

    id: str
    question: str
    answer_markdown: str
    answer_rich_text: str | None = None
    lecturer_only: bool = False
    metadata_filter: FaqMetadata
    source: str = "manual"
    deleted_at: datetime | None = None


async def get_faq_entities(faq_ids: list[str]) -> dict[str, FaqEntityCacheEntry]:
    """Hydrate exact FAQ IDs through Redis, querying Mongo only for misses."""
    unique_ids = list(dict.fromkeys(faq_id for faq_id in faq_ids if faq_id))
    if not unique_ids:
        return {}

    redis = get_redis_client()
    await redis.connect()
    cached_values = await redis.mget_json([faq_entity_key(faq_id) for faq_id in unique_ids])
    entities: dict[str, FaqEntityCacheEntry] = {}
    missing_ids: list[str] = []
    for faq_id, payload in zip(unique_ids, cached_values):
        if payload is None:
            missing_ids.append(faq_id)
            continue
        try:
            entry = FaqEntityCacheEntry.model_validate(payload)
        except ValidationError:
            missing_ids.append(faq_id)
            continue
        if entry.id != faq_id:
            missing_ids.append(faq_id)
            continue
        entities[faq_id] = entry

    if not missing_ids:
        return entities

    faq_svc = await get_faq_service()
    faqs = await faq_svc.get_faqs_by_ids(missing_ids)
    writes = []
    for faq in faqs:
        faq_id = str(faq.id)
        entry = FaqEntityCacheEntry(
            id=faq_id,
            question=faq.question or "",
            answer_markdown=faq.answer_markdown or "",
            answer_rich_text=faq.answer_rich_text,
            lecturer_only=bool(faq.lecturer_only),
            metadata_filter=faq.metadata_filter,
            source=faq.source,
            deleted_at=faq.deleted_at,
        )
        entities[faq_id] = entry
        writes.append(redis.set_json(
            faq_entity_key(faq_id),
            entry,
            ex=settings.RAG_ENTITY_CACHE_TTL_SECONDS,
        ))
    if writes:
        await asyncio.gather(*writes)
    return entities


async def hydrate_faq_candidate_docs(faq_candidates: list, limit: int = 3) -> list:
    """
    Fetch FaqDocument cho các FaqCandidate từ traversal.
    Corpus prefilter đã lọc FAQ active trước traversal; ở đây chỉ hydrate theo ID
    và giữ thứ tự ưu tiên từ traversal. Best-effort: FAQ lỗi/không tồn tại thì bỏ qua.
    """
    if not faq_candidates:
        return []

    valid_ids = []
    for cand in faq_candidates[:limit]:
        if cand.faq_id:
            valid_ids.append(cand.faq_id)

    if not valid_ids:
        return []

    try:
        faq_map = await get_faq_entities(valid_ids)
    except Exception as e:
        logger.warning("[FAQ] Failed to hydrate FAQ candidates: %s", e)
        return []

    faq_docs = []
    for cand in faq_candidates[:limit]:
        faq = faq_map.get(cand.faq_id)
        if faq:
            faq_docs.append(faq)

    return faq_docs


def build_faq_context(faq_docs: list) -> str:
    """Dựng khối ngữ cảnh FAQ để nhồi vào prompt PageIndex khi FAQ không đủ trả lời trực tiếp."""
    if not faq_docs:
        return ""
    faq_parts = [
        f"**Related question:** {f.question}\n**Supporting answer:** {f.answer_markdown}"
        for f in faq_docs
    ]
    return (
        "## Supplemental FAQ context for document research:\n\n"
        + "\n\n---\n\n".join(faq_parts)
        + "\n\n"
    )
