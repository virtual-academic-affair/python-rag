from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.modules.rag.cache import (
    CORPUS_REVISION_KEY,
    FILE_ELIGIBILITY_REVISION_KEY,
    FAQ_ELIGIBILITY_REVISION_KEY,
    RagCacheService,
    allowed_ids_key,
    canonical_metadata_hash,
)


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.deleted = []

    async def connect(self):
        return None

    async def get_int(self, key):
        value = self.values.get(key)
        return int(value) if value is not None else None

    async def incr(self, key):
        self.values[key] = int(self.values.get(key, 0)) + 1
        return self.values[key]

    async def get_json(self, key):
        return self.values.get(key)

    async def set_json(self, key, value, ex=None):
        if isinstance(value, list):
            self.values[key] = [
                item.model_dump(mode="json") if hasattr(item, "model_dump") else item
                for item in value
            ]
        else:
            self.values[key] = value

    async def delete_many(self, keys):
        self.deleted.extend(keys)
        for key in keys:
            self.values.pop(key, None)
        return True


def test_metadata_hash_is_canonical_and_scopes_are_separate():
    first = {"academic_year": {"to": 2026, "from": 2025}, "type": "ctdt"}
    second = {"type": "ctdt", "academic_year": {"from": 2025, "to": 2026}}

    assert canonical_metadata_hash(first) == canonical_metadata_hash(second)
    student = allowed_ids_key("file", 3, "student", first)
    privileged = allowed_ids_key("file", 3, "lecture", second)
    assert ":student:" in student
    assert ":privileged:" in privileged
    assert student != privileged
    assert "v2" not in student
    assert ":cache:" not in student


@pytest.mark.asyncio
async def test_allowed_ids_cache_reuses_payload_and_separates_entity_revisions():
    redis = FakeRedis()
    cache = RagCacheService(redis)
    file_loader = AsyncMock(return_value={"file-a"})
    faq_loader = AsyncMock(return_value={"faq-a"})

    assert await cache.get_allowed_ids("file", {"type": "ctdt"}, "student", file_loader) == {"file-a"}
    assert await cache.get_allowed_ids("file", {"type": "ctdt"}, "student", file_loader) == {"file-a"}
    assert await cache.get_allowed_ids("faq", {"type": "ctdt"}, "student", faq_loader) == {"faq-a"}

    file_loader.assert_awaited_once()
    faq_loader.assert_awaited_once()
    assert redis.values[FILE_ELIGIBILITY_REVISION_KEY] == 1
    assert redis.values[FAQ_ELIGIBILITY_REVISION_KEY] == 1


@pytest.mark.asyncio
async def test_corpus_revision_switches_payload_and_entity_invalidation_is_exact():
    redis = FakeRedis()
    cache = RagCacheService(redis)
    first_loader = AsyncMock(return_value=[
        SimpleNamespace(
            node_key="first",
            title="First",
            summary="",
            direct_file_ids=[],
            direct_faq_ids=[],
            subtree_file_ids=[],
            subtree_faq_ids=[],
            child_keys=[],
            parent_key=None,
            file_count=0,
            faq_count=0,
        )
    ])

    first = await cache.get_corpus_nodes(first_loader)
    assert first[0].node_key == "first"
    assert redis.values[CORPUS_REVISION_KEY] == 1

    await cache.bump_corpus_revision()
    second_loader = AsyncMock(return_value=[])
    assert await cache.get_corpus_nodes(second_loader) == []
    second_loader.assert_awaited_once()
    assert redis.values[CORPUS_REVISION_KEY] == 2

    await cache.invalidate_file("A")
    await cache.invalidate_faq("A")
    assert redis.deleted == ["rag:file:A", "rag:faq:A"]


@pytest.mark.asyncio
async def test_unavailable_redis_falls_back_to_loader_and_invalidation_stays_best_effort():
    redis = FakeRedis()
    redis.get_int = AsyncMock(return_value=None)
    redis.incr = AsyncMock(return_value=None)
    redis.get_json = AsyncMock(return_value=None)
    redis.delete_many = AsyncMock(return_value=False)
    cache = RagCacheService(redis)
    loader = AsyncMock(return_value={"file-a"})

    assert await cache.get_allowed_ids("file", None, "student", loader) == {"file-a"}
    await cache.invalidate_file("A")
    await cache.bump_file_eligibility_revision()

    loader.assert_awaited_once()
