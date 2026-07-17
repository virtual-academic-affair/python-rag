from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import ConflictException
from app.modules.faq.models.faq import FaqDocument
from app.modules.faq.repositories.faq_repository import FaqRepository
from app.modules.faq.services.faq_service import FaqService


def _faq(**overrides):
    values = {
        "id": "faq1",
        "question": "Học phí?",
        "question_unaccented": "hoc phi?",
        "answer_unaccented": "tra loi",
        "answer_markdown": "Trả lời",
        "answer_rich_text": "<p>Trả lời</p>",
        "view_count": 0,
        "source": "manual",
        "deleted_at": None,
        "deleted_by": None,
        "deleted_corpus_node_keys": [],
    }
    values.update(overrides)
    return FaqDocument.model_construct(**values)


def test_faq_active_query_always_requires_deleted_at_null():
    assert FaqRepository._active_query() == {"deleted_at": None}
    assert FaqRepository._active_query({"lecturer_only": False}) == {
        "$and": [{"deleted_at": None}, {"lecturer_only": False}]
    }


@pytest.mark.asyncio
async def test_delete_faq_soft_deletes_before_unindex():
    service = FaqService.__new__(FaqService)
    doc = _faq()
    repo = MagicMock()
    repo.find_by_id_including_deleted = AsyncMock(return_value=doc)
    repo.soft_delete = AsyncMock(return_value=True)
    service._faq_repo = repo

    corpus = MagicMock()
    corpus.get_payload_node_keys = AsyncMock(return_value=["tuition"])
    linker = MagicMock()
    linker.unindex_faq = AsyncMock()

    with patch("app.modules.faq.services.faq_service.get_corpus_service", return_value=corpus), patch(
        "app.modules.faq.services.faq_service.get_corpus_linker", return_value=linker
    ):
        assert await service.delete_faq("faq1", "admin1") is True

    repo.soft_delete.assert_awaited_once_with(
        "faq1",
        deleted_by="admin1",
        corpus_node_keys=["tuition"],
    )
    linker.unindex_faq.assert_awaited_once_with("faq1")
    repo.delete.assert_not_called()


@pytest.mark.asyncio
async def test_restore_faq_uses_llm_when_saved_topics_are_missing():
    service = FaqService.__new__(FaqService)
    deleted = _faq(
        deleted_at=datetime.now(timezone.utc),
        deleted_corpus_node_keys=["removed-topic"],
    )
    restored = _faq()
    repo = MagicMock()
    repo.find_by_id_including_deleted = AsyncMock(return_value=deleted)
    repo.find_by_unaccented_question = AsyncMock(return_value=None)
    repo.restore = AsyncMock(return_value=True)
    repo.find_by_id = AsyncMock(return_value=restored)
    service._faq_repo = repo

    corpus = MagicMock()
    corpus.existing_node_keys = AsyncMock(return_value=[])
    linker = MagicMock()
    linker.index_faq = AsyncMock(return_value=["new-topic"])
    linker.unindex_faq = AsyncMock()

    with patch("app.modules.faq.services.faq_service.get_corpus_service", return_value=corpus), patch(
        "app.modules.faq.services.faq_service.get_corpus_linker", return_value=linker
    ):
        result = await service.restore_faq("faq1")

    assert result is restored
    linker.index_faq.assert_awaited_once()
    repo.restore.assert_awaited_once_with("faq1")


@pytest.mark.asyncio
async def test_restore_faq_rejects_duplicate_question():
    service = FaqService.__new__(FaqService)
    deleted = _faq(deleted_at=datetime.now(timezone.utc))
    repo = MagicMock()
    repo.find_by_id_including_deleted = AsyncMock(return_value=deleted)
    repo.find_by_unaccented_question = AsyncMock(return_value=_faq(id="faq2"))
    service._faq_repo = repo

    with pytest.raises(ConflictException, match="already exists"):
        await service.restore_faq("faq1")
