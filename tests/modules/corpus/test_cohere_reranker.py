from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.modules.rag.query.retrieval.rerank.cohere_reranker import CohereRetrievalReranker


def _candidates():
    return [
        {"file_id": "f1", "file_name": "A", "doc_description": "Mô tả A"},
        {"file_id": "f2", "file_name": "B", "doc_description": "Mô tả B"},
        {"file_id": "f3", "file_name": "C", "doc_description": "Mô tả C"},
    ]


def _faq_doc(question: str, answer: str):
    return SimpleNamespace(
        id=f"faq-{question}",
        question=question,
        answer_markdown=answer,
        metadata_filter=None,
    )


@pytest.fixture(autouse=True)
def _cohere_settings(monkeypatch):
    monkeypatch.setattr("app.core.config.settings.COHERE_API_KEY", "test-key")
    monkeypatch.setattr("app.core.config.settings.COHERE_RERANK_ENABLED", True)
    monkeypatch.setattr("app.core.config.settings.COHERE_RERANK_MODEL", "rerank-v4.0-fast")
    monkeypatch.setattr("app.core.config.settings.COHERE_RERANK_MAX_CANDIDATES", 20)
    monkeypatch.setattr("app.core.config.settings.COHERE_RERANK_MAX_TOKENS_PER_DOC", 1024)
    monkeypatch.setattr("app.core.config.settings.COHERE_RERANK_TIMEOUT_SECONDS", 10.0)


@pytest.mark.asyncio
async def test_cohere_reranker_applies_valid_file_order():
    client = AsyncMock()
    client.rerank = AsyncMock(return_value=[2, 0, 1])

    ranked = await CohereRetrievalReranker(client=client).rerank_files("câu hỏi", _candidates())

    assert [c["file_id"] for c in ranked] == ["f3", "f1", "f2"]
    client.rerank.assert_awaited_once()
    call_kwargs = client.rerank.await_args.kwargs
    assert call_kwargs["query"] == "câu hỏi"
    assert call_kwargs["top_n"] == 3
    assert "type: file" in call_kwargs["documents"][0]
    assert "Mô tả A" in call_kwargs["documents"][0]


@pytest.mark.asyncio
async def test_cohere_reranker_falls_back_when_disabled_or_missing_key(monkeypatch):
    original = _candidates()
    client = AsyncMock()
    client.rerank = AsyncMock(return_value=[2, 0, 1])
    monkeypatch.setattr("app.core.config.settings.COHERE_RERANK_ENABLED", False)

    ranked = await CohereRetrievalReranker(client=client).rerank_files("câu hỏi", original)

    assert ranked == original
    client.rerank.assert_not_awaited()

    monkeypatch.setattr("app.core.config.settings.COHERE_RERANK_ENABLED", True)
    monkeypatch.setattr("app.core.config.settings.COHERE_API_KEY", None)

    ranked = await CohereRetrievalReranker(client=client).rerank_files("câu hỏi", original)

    assert ranked == original
    client.rerank.assert_not_awaited()


@pytest.mark.asyncio
async def test_cohere_reranker_falls_back_when_client_returns_none():
    original = _candidates()
    client = AsyncMock()
    client.rerank = AsyncMock(return_value=None)

    ranked = await CohereRetrievalReranker(client=client).rerank_files("câu hỏi", original)

    assert ranked == original


@pytest.mark.asyncio
async def test_cohere_reranker_reranks_faqs_with_limit():
    faq_docs = [
        _faq_doc("q1", "a1"),
        _faq_doc("q2", "a2"),
        _faq_doc("q3", "a3"),
    ]
    client = AsyncMock()
    client.rerank = AsyncMock(return_value=[2, 0])

    ranked = await CohereRetrievalReranker(client=client).rerank_faqs("câu hỏi", faq_docs, limit=2)

    assert [faq.question for faq in ranked] == ["q3", "q1"]
    call_kwargs = client.rerank.await_args.kwargs
    assert call_kwargs["top_n"] == 2
    assert "type: faq" in call_kwargs["documents"][0]
    assert "question: q1" in call_kwargs["documents"][0]
    assert "answer: a1" in call_kwargs["documents"][0]


@pytest.mark.asyncio
async def test_cohere_reranker_scores_candidates_beyond_the_legacy_twenty_item_cutoff(monkeypatch):
    monkeypatch.setattr("app.core.config.settings.COHERE_RERANK_MAX_CANDIDATES", 100)
    candidates = [
        {"file_id": f"f{i}", "file_name": f"File {i}", "doc_description": f"Description {i}"}
        for i in range(25)
    ]
    client = AsyncMock()
    client.rerank = AsyncMock(return_value=[24, 3])

    ranked = await CohereRetrievalReranker(client=client).rerank_files(
        "câu hỏi",
        candidates,
        limit=2,
    )

    assert [candidate["file_id"] for candidate in ranked] == ["f24", "f3"]
    assert len(client.rerank.await_args.kwargs["documents"]) == 25
