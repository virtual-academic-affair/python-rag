from app.core.config import settings
from app.integrations.pageindex import utils as pageindex_utils
from app.integrations.pageindex.utils import ConfigLoader


def test_pageindex_defaults_to_shared_llm_model(monkeypatch):
    monkeypatch.setattr(settings, "LLM_MODEL", "gemini/test-shared-model")

    config = ConfigLoader().load()

    assert config.model == "gemini/test-shared-model"
    assert config.retrieve_model == "gemini/test-shared-model"


def test_pageindex_completion_uses_shared_llm_api_key(monkeypatch):
    captured = {}

    class Response:
        class Choice:
            class Message:
                content = "ok"

            message = Message()
            finish_reason = "stop"

        choices = [Choice()]

    def fake_completion(**kwargs):
        captured.update(kwargs)
        return Response()

    monkeypatch.setattr(settings, "LLM_API_KEY", "test-provider-key")
    monkeypatch.setattr(pageindex_utils.litellm, "completion", fake_completion)

    assert pageindex_utils.llm_completion("openrouter/test/model", "hello") == "ok"
    assert captured["api_key"] == "test-provider-key"
