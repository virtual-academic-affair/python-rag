"""Shared, best-effort Redis cache contracts for RAG retrieval."""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.core.config import settings
from app.integrations.redis.client import RedisClient, get_redis_client

if TYPE_CHECKING:
    from app.modules.corpus.models.corpus_node import CorpusNodeDocument

logger = logging.getLogger(__name__)

CORPUS_REVISION_KEY = "rag:revision:corpus"
FILE_ELIGIBILITY_REVISION_KEY = "rag:revision:file_eligibility"
FAQ_ELIGIBILITY_REVISION_KEY = "rag:revision:faq_eligibility"

AccessScope = Literal["student", "privileged"]
EligibilityKind = Literal["file", "faq"]


class CorpusNodeCacheEntry(BaseModel):
    """The retrieval-facing subset of a Corpus node stored in Redis."""

    model_config = ConfigDict(extra="forbid")

    node_key: str
    title: str = ""
    summary: str = ""
    direct_file_ids: list[str] = Field(default_factory=list)
    direct_faq_ids: list[str] = Field(default_factory=list)
    subtree_file_ids: list[str] = Field(default_factory=list)
    subtree_faq_ids: list[str] = Field(default_factory=list)
    child_keys: list[str] = Field(default_factory=list)
    parent_key: str | None = None
    file_count: int = 0
    faq_count: int = 0

    @classmethod
    def from_document(cls, node: "CorpusNodeDocument") -> "CorpusNodeCacheEntry":
        return cls.model_validate({name: getattr(node, name) for name in cls.model_fields})


def access_scope_for_role(user_role: str | None) -> AccessScope:
    return "privileged" if user_role in {"admin", "lecture"} else "student"


def canonical_metadata_hash(metadata_filter: dict[str, Any] | None) -> str:
    canonical = json.dumps(
        metadata_filter or {},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def corpus_payload_key(revision: int) -> str:
    return f"rag:corpus:{revision}"


def allowed_ids_key(
    kind: EligibilityKind,
    revision: int,
    user_role: str | None,
    metadata_filter: dict[str, Any] | None,
) -> str:
    return (
        f"rag:allowed:{kind}:{revision}:{access_scope_for_role(user_role)}:"
        f"{canonical_metadata_hash(metadata_filter)}"
    )


def file_entity_key(file_id: str) -> str:
    return f"rag:file:{file_id}"


def faq_entity_key(faq_id: str) -> str:
    return f"rag:faq:{faq_id}"


class RagCacheService:
    """Small cache facade that always falls back to the source of truth."""

    def __init__(self, redis: RedisClient | None = None):
        self.redis = redis or get_redis_client()

    async def _connect(self) -> bool:
        if not settings.REDIS_ENABLED:
            return False
        await self.redis.connect()
        return True

    async def _revision(self, key: str) -> int | None:
        if not await self._connect():
            return None
        revision = await self.redis.get_int(key)
        if revision is not None:
            return revision
        return await self.redis.incr(key)

    async def get_corpus_nodes(
        self,
        loader: Callable[[], Awaitable[list["CorpusNodeDocument"]]],
    ) -> list[CorpusNodeCacheEntry]:
        revision = await self._revision(CORPUS_REVISION_KEY)
        if revision is not None:
            key = corpus_payload_key(revision)
            cached = await self.redis.get_json(key)
            if isinstance(cached, list):
                try:
                    return [CorpusNodeCacheEntry.model_validate(item) for item in cached]
                except ValidationError as exc:
                    logger.warning("[RAG cache] invalid_corpus_payload key=%s error=%s", key, exc)

        nodes = [CorpusNodeCacheEntry.from_document(node) for node in await loader()]
        if revision is not None:
            await self.redis.set_json(
                corpus_payload_key(revision),
                nodes,
                ex=settings.RAG_CORPUS_CACHE_TTL_SECONDS,
            )
        return nodes

    async def get_allowed_ids(
        self,
        kind: EligibilityKind,
        metadata_filter: dict[str, Any] | None,
        user_role: str | None,
        loader: Callable[[], Awaitable[set[str]]],
    ) -> set[str]:
        revision_key = (
            FILE_ELIGIBILITY_REVISION_KEY
            if kind == "file"
            else FAQ_ELIGIBILITY_REVISION_KEY
        )
        revision = await self._revision(revision_key)
        key = (
            allowed_ids_key(kind, revision, user_role, metadata_filter)
            if revision is not None
            else None
        )
        if key:
            cached = await self.redis.get_json(key)
            if isinstance(cached, list) and all(isinstance(item, str) for item in cached):
                return set(cached)

        allowed_ids = await loader()
        if key:
            await self.redis.set_json(
                key,
                sorted(allowed_ids),
                ex=settings.RAG_ALLOWED_IDS_CACHE_TTL_SECONDS,
            )
        return allowed_ids

    async def _bump(self, key: str) -> int | None:
        if not settings.REDIS_ENABLED:
            return None
        if not await self._connect():
            logger.warning("[RAG cache] revision_bypass key=%s reason=redis_unavailable", key)
            return None
        revision = await self.redis.incr(key)
        if revision is None:
            logger.warning("[RAG cache] revision_failed key=%s", key)
        return revision

    async def bump_corpus_revision(self) -> int | None:
        return await self._bump(CORPUS_REVISION_KEY)

    async def bump_file_eligibility_revision(self) -> int | None:
        return await self._bump(FILE_ELIGIBILITY_REVISION_KEY)

    async def bump_faq_eligibility_revision(self) -> int | None:
        return await self._bump(FAQ_ELIGIBILITY_REVISION_KEY)

    async def invalidate_file(self, file_id: str) -> None:
        await self._delete_exact([file_entity_key(file_id)])

    async def invalidate_faq(self, faq_id: str) -> None:
        await self._delete_exact([faq_entity_key(faq_id)])

    async def _delete_exact(self, keys: list[str]) -> None:
        if not settings.REDIS_ENABLED:
            return
        if not await self._connect():
            logger.warning("[RAG cache] delete_bypass keys=%s reason=redis_unavailable", keys)
            return
        if not await self.redis.delete_many(keys):
            logger.warning("[RAG cache] delete_failed keys=%s", keys)


_rag_cache_service: RagCacheService | None = None


def get_rag_cache_service() -> RagCacheService:
    global _rag_cache_service
    if _rag_cache_service is None:
        _rag_cache_service = RagCacheService()
    return _rag_cache_service
