from types import SimpleNamespace

import pytest

from app.integrations.cohere.client import CohereRerankClient


class _FakeCohereSdkClient:
    last_payload = None
    last_kwargs = None
    response_data = None
    side_effect = None
    called = False
    closed = False

    def __init__(self, **kwargs):
        self.__class__.last_kwargs = kwargs

    async def rerank(self, **payload):
        self.__class__.called = True
        self.__class__.last_payload = payload
        if self.__class__.side_effect:
            raise self.__class__.side_effect
        return self.__class__.response_data

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        self.__class__.closed = True


@pytest.fixture(autouse=True)
def _reset_fake_client(monkeypatch):
    _FakeCohereSdkClient.last_payload = None
    _FakeCohereSdkClient.last_kwargs = None
    _FakeCohereSdkClient.response_data = None
    _FakeCohereSdkClient.side_effect = None
    _FakeCohereSdkClient.called = False
    _FakeCohereSdkClient.closed = False
    monkeypatch.setattr(
        "app.integrations.cohere.client.cohere.AsyncClientV2",
        _FakeCohereSdkClient,
    )


@pytest.fixture(autouse=True)
def _cohere_settings(monkeypatch):
    monkeypatch.setattr("app.core.config.settings.COHERE_API_KEY", "test-key")
    monkeypatch.setattr("app.core.config.settings.COHERE_RERANK_ENABLED", True)
    monkeypatch.setattr("app.core.config.settings.COHERE_RERANK_MODEL", "rerank-v4.0-fast")
    monkeypatch.setattr("app.core.config.settings.COHERE_RERANK_MAX_TOKENS_PER_DOC", 1024)
    monkeypatch.setattr("app.core.config.settings.COHERE_RERANK_TIMEOUT_SECONDS", 10.0)


@pytest.mark.asyncio
async def test_cohere_client_returns_indexes_and_sends_configured_payload():
    _FakeCohereSdkClient.response_data = SimpleNamespace(
        results=[
            SimpleNamespace(index=2, relevance_score=0.9),
            SimpleNamespace(index=0, relevance_score=0.8),
        ]
    )

    indexes = await CohereRerankClient().rerank(
        query="câu hỏi",
        documents=["a", "b", "c"],
        top_n=2,
    )

    assert indexes == [2, 0]
    assert _FakeCohereSdkClient.last_kwargs["api_key"] == "test-key"
    assert _FakeCohereSdkClient.last_kwargs["timeout"] == 10.0
    assert _FakeCohereSdkClient.last_payload == {
        "model": "rerank-v4.0-fast",
        "query": "câu hỏi",
        "documents": ["a", "b", "c"],
        "top_n": 2,
        "max_tokens_per_doc": 1024,
    }
    assert _FakeCohereSdkClient.closed is True


@pytest.mark.asyncio
async def test_cohere_client_returns_none_when_disabled_or_missing_key(monkeypatch):
    monkeypatch.setattr("app.core.config.settings.COHERE_RERANK_ENABLED", False)

    indexes = await CohereRerankClient().rerank(
        query="câu hỏi",
        documents=["a", "b"],
        top_n=2,
    )

    assert indexes is None
    assert _FakeCohereSdkClient.called is False

    monkeypatch.setattr("app.core.config.settings.COHERE_RERANK_ENABLED", True)
    monkeypatch.setattr("app.core.config.settings.COHERE_API_KEY", None)

    indexes = await CohereRerankClient().rerank(
        query="câu hỏi",
        documents=["a", "b"],
        top_n=2,
    )

    assert indexes is None
    assert _FakeCohereSdkClient.called is False


@pytest.mark.asyncio
async def test_cohere_client_returns_none_on_error_or_malformed_response():
    _FakeCohereSdkClient.side_effect = RuntimeError("down")

    indexes = await CohereRerankClient().rerank(
        query="câu hỏi",
        documents=["a", "b", "c"],
        top_n=2,
    )

    assert indexes is None
    assert _FakeCohereSdkClient.closed is True

    _FakeCohereSdkClient.side_effect = None
    _FakeCohereSdkClient.response_data = SimpleNamespace(results=[SimpleNamespace(index=99)])

    indexes = await CohereRerankClient().rerank(
        query="câu hỏi",
        documents=["a", "b", "c"],
        top_n=1,
    )

    assert indexes is None

    _FakeCohereSdkClient.response_data = SimpleNamespace(results=[SimpleNamespace(index=1)])

    indexes = await CohereRerankClient().rerank(
        query="câu hỏi",
        documents=["a", "b", "c"],
        top_n=2,
    )

    assert indexes is None
