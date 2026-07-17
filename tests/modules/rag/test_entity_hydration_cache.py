from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.metadata.models.value_objects import FaqMetadata
from app.modules.rag.query.retrieval.hydration.faq_hydrator import (
    FaqEntityCacheEntry,
    get_faq_entities,
)
from app.modules.rag.query.retrieval.hydration.file_hydrator import (
    FileEntityCacheEntry,
    get_file_entities,
)


class EntityRedis:
    def __init__(self, payloads):
        self.payloads = payloads
        self.writes = {}

    async def connect(self):
        return None

    async def mget_json(self, keys):
        return [self.payloads.get(key) for key in keys]

    async def set_json(self, key, value, ex=None):
        self.writes[key] = value


@pytest.mark.asyncio
async def test_partial_file_mget_queries_mongo_only_for_misses_and_preserves_lookup():
    cached = FileEntityCacheEntry(
        file_id="A",
        file_name="Cached A",
        storage_path="a.pdf",
        markdown_storage_path="a.md",
    )
    redis = EntityRedis({"rag:file:A": cached.model_dump(mode="json")})
    file_b = SimpleNamespace(
        id="B",
        display_name="Mongo B",
        original_filename="b.pdf",
        storage_path="b.pdf",
        table_of_contents=["B"],
        custom_metadata=None,
        lecturer_only=False,
    )
    toc_b = SimpleNamespace(
        file_id="B",
        markdown_storage_path="b.md",
        doc_name="B",
        doc_description="Description B",
        line_count=2,
        structure=[],
    )
    file_service = MagicMock()
    file_service.get_files_by_ids = AsyncMock(return_value=[file_b])
    toc_repo = MagicMock()
    toc_repo.find_by_file_ids = AsyncMock(return_value=[toc_b])

    with patch(
        "app.modules.rag.query.retrieval.hydration.file_hydrator.get_redis_client",
        return_value=redis,
    ), patch(
        "app.modules.rag.query.retrieval.hydration.file_hydrator.get_file_service",
        return_value=file_service,
    ), patch(
        "app.modules.rag.query.retrieval.hydration.file_hydrator.FileTocTreeRepository",
        return_value=toc_repo,
    ):
        entities = await get_file_entities(["B", "A", "B"])

    file_service.get_files_by_ids.assert_awaited_once_with(["B"])
    toc_repo.find_by_file_ids.assert_awaited_once_with(["B"])
    assert entities["A"].file_name == "Cached A"
    assert entities["B"].file_name == "Mongo B"
    assert set(redis.writes) == {"rag:file:B"}


@pytest.mark.asyncio
async def test_partial_faq_mget_queries_mongo_only_for_misses():
    cached = FaqEntityCacheEntry(
        id="A",
        question="Cached A",
        answer_markdown="A",
        metadata_filter=FaqMetadata(),
    )
    redis = EntityRedis({"rag:faq:A": cached.model_dump(mode="json")})
    faq_b = SimpleNamespace(
        id="B",
        question="Mongo B",
        answer_markdown="B",
        answer_rich_text=None,
        lecturer_only=False,
        metadata_filter=FaqMetadata(),
        source="manual",
        deleted_at=None,
    )
    faq_service = MagicMock()
    faq_service.get_faqs_by_ids = AsyncMock(return_value=[faq_b])

    with patch(
        "app.modules.rag.query.retrieval.hydration.faq_hydrator.get_redis_client",
        return_value=redis,
    ), patch(
        "app.modules.rag.query.retrieval.hydration.faq_hydrator.get_faq_service",
        AsyncMock(return_value=faq_service),
    ):
        entities = await get_faq_entities(["A", "B"])

    faq_service.get_faqs_by_ids.assert_awaited_once_with(["B"])
    assert entities["A"].question == "Cached A"
    assert entities["B"].question == "Mongo B"
    assert set(redis.writes) == {"rag:faq:B"}


@pytest.mark.asyncio
async def test_legacy_faq_cache_entry_with_candidate_id_is_reloaded():
    legacy_payload = FaqEntityCacheEntry(
        id="A",
        question="Stale A",
        answer_markdown="Stale",
        metadata_filter=FaqMetadata(),
    ).model_dump(mode="json")
    legacy_payload["candidate_id"] = "retired-candidate"
    redis = EntityRedis({"rag:faq:A": legacy_payload})
    faq_a = SimpleNamespace(
        id="A",
        question="Mongo A",
        answer_markdown="Current",
        answer_rich_text=None,
        lecturer_only=False,
        metadata_filter=FaqMetadata(),
        source="synthesized",
        deleted_at=None,
    )
    faq_service = MagicMock()
    faq_service.get_faqs_by_ids = AsyncMock(return_value=[faq_a])

    with patch(
        "app.modules.rag.query.retrieval.hydration.faq_hydrator.get_redis_client",
        return_value=redis,
    ), patch(
        "app.modules.rag.query.retrieval.hydration.faq_hydrator.get_faq_service",
        AsyncMock(return_value=faq_service),
    ):
        entities = await get_faq_entities(["A"])

    faq_service.get_faqs_by_ids.assert_awaited_once_with(["A"])
    assert entities["A"].question == "Mongo A"
    assert entities["A"].source == "synthesized"
    assert "candidate_id" not in redis.writes["rag:faq:A"].model_dump()
