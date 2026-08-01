from unittest.mock import patch
import pytest

from app.core.config import Settings
from app.integrations.llm.gateway import LLMGateway
from app.integrations.pageindex.utils import _resolve_model_and_kwargs


def test_llm_gateway_request_kwargs_without_base_url():
    test_settings = Settings(
        LLM_API_KEY="test-key",
        LLM_MODEL="gemini/gemini-2.5-flash",
        LLM_BASE_URL=None,
    )
    with patch("app.integrations.llm.gateway.settings", test_settings):
        gateway = LLMGateway()
        kwargs = gateway._request_kwargs(
            messages=[{"role": "user", "content": "hello"}],
            model=None,
            temperature=0.0,
            response_format=None,
            tools=None,
            stream=False,
        )
        assert kwargs["model"] == "gemini/gemini-2.5-flash"
        assert "api_base" not in kwargs


def test_llm_gateway_request_kwargs_with_custom_base_url_and_unprefixed_model():
    test_settings = Settings(
        LLM_API_KEY="sk-custom-key",
        LLM_MODEL="Qwen3.6-27B",
        LLM_BASE_URL="https://ai-fit.hcmus.edu.vn/openai",
    )
    with patch("app.integrations.llm.gateway.settings", test_settings):
        gateway = LLMGateway()
        kwargs = gateway._request_kwargs(
            messages=[{"role": "user", "content": "hello"}],
            model=None,
            temperature=0.0,
            response_format=None,
            tools=None,
            stream=False,
        )
        assert kwargs["model"] == "openai/Qwen3.6-27B"
        assert kwargs["api_base"] == "https://ai-fit.hcmus.edu.vn/openai"


def test_llm_gateway_request_kwargs_preserves_existing_provider_prefix():
    test_settings = Settings(
        LLM_API_KEY="sk-custom-key",
        LLM_MODEL="openai/custom-model",
        LLM_BASE_URL="https://custom-gateway.local/v1",
    )
    with patch("app.integrations.llm.gateway.settings", test_settings):
        gateway = LLMGateway()
        kwargs = gateway._request_kwargs(
            messages=[{"role": "user", "content": "hello"}],
            model=None,
            temperature=0.0,
            response_format=None,
            tools=None,
            stream=False,
        )
        assert kwargs["model"] == "openai/custom-model"
        assert kwargs["api_base"] == "https://custom-gateway.local/v1"


def test_pageindex_resolve_model_and_kwargs():
    test_settings = Settings(
        LLM_API_KEY="sk-test",
        LLM_MODEL="Qwen3.6-27B",
        LLM_BASE_URL="https://ai-fit.hcmus.edu.vn/openai",
    )
    with patch("app.integrations.pageindex.utils.settings", test_settings):
        model, kwargs = _resolve_model_and_kwargs("Qwen3.6-27B")
        assert model == "openai/Qwen3.6-27B"
        assert kwargs == {"api_base": "https://ai-fit.hcmus.edu.vn/openai"}
