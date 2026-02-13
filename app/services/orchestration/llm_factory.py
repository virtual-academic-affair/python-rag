import os
import logging
from typing import Any, Dict, Optional

from google import genai
from google.genai import types

logger = logging.getLogger(__name__)


def _env_int_or_none(name: str, default: Optional[int]) -> Optional[int]:
    raw = os.getenv(name)
    if raw is None:
        return default
    raw = raw.strip()
    if raw == "":
        return None
    try:
        return int(raw)
    except ValueError:
        logger.warning("Invalid %s=%r; using default=%r", name, raw, default)
        return default


class GeminiResponse:
    def __init__(self, content: str):
        self.content = content


class GeminiGenAIChat:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        temperature: float,
        thinking_level: Optional[str] = None,
        max_output_tokens: Optional[int] = None,
        request_timeout: Optional[int] = None,
    ):
        self._client = genai.Client(api_key=api_key)
        self._model = model
        self._temperature = temperature
        self._thinking_level = thinking_level
        self._max_output_tokens = max_output_tokens
        self._request_timeout = request_timeout or int(os.getenv("GENAI_REQUEST_TIMEOUT", "60"))

    def _build_config(self) -> types.GenerateContentConfig:
        kwargs: Dict[str, Any] = {}
        if self._temperature is not None:
            kwargs["temperature"] = self._temperature
        if self._max_output_tokens is not None:
            kwargs["max_output_tokens"] = self._max_output_tokens
        if self._thinking_level:
            # google-genai uses nested thinking_config with include_thoughts
            kwargs["thinking_config"] = types.ThinkingConfig(include_thoughts=True)
        return types.GenerateContentConfig(**kwargs)

    async def ainvoke(self, inputs: Dict[str, Any]) -> GeminiResponse:
        # LangChain prompts pass a dict with variables already formatted into the HumanMessage.
        # We standardize on accepting either {"title":...,"content":...} style or direct {"text":...}.
        title = inputs.get("title")
        content = inputs.get("content")
        content_lines = inputs.get("content_lines")

        if content_lines is not None and title is not None:
            prompt = f"Title: {title}\n\nCONTENT (numbered lines):\n{content_lines}"
        elif title is not None and content is not None:
            prompt = f"Title: {title}\n\nContent: {content}"
        else:
            prompt = inputs.get("text") or ""

        model_name = self._model
        if model_name and not model_name.startswith("models/"):
            model_name = f"models/{model_name}"

        resp = self._client.models.generate_content(
            model=model_name,
            contents=prompt,
            config=self._build_config(),
        )
        return GeminiResponse(resp.text or "")


class GeminiPromptChain:
    def __init__(self, prompt: Any, llm: GeminiGenAIChat):
        self._prompt = prompt
        self._llm = llm

    async def ainvoke(self, inputs: Dict[str, Any]) -> GeminiResponse:
        msgs = self._prompt.format_messages(**inputs)
        system_parts = [m.content for m in msgs if getattr(m, "type", None) == "system"]
        human_parts = [m.content for m in msgs if getattr(m, "type", None) == "human"]
        combined = "\n\n".join([*system_parts, *human_parts]).strip()
        return await self._llm.ainvoke({"text": combined})


def build_chat_llm(
    *,
    api_key: str,
    model: str,
    temperature: float,
    thinking_level: Optional[str] = None,
    max_output_tokens: Optional[int] = None,
    request_timeout: Optional[int] = None,
) -> GeminiGenAIChat:
    logger.info(
        "Building google-genai client model=%s temperature=%s thinking=%s max_tokens=%s timeout=%s",
        model,
        temperature,
        thinking_level,
        max_output_tokens,
        request_timeout,
    )
    return GeminiGenAIChat(
        api_key=api_key,
        model=model,
        temperature=temperature,
        thinking_level=thinking_level,
        max_output_tokens=max_output_tokens,
        request_timeout=request_timeout,
    )


def build_classification_llm(
    *,
    api_key: str,
    model: str,
    temperature: float,
    thinking_level: Optional[str] = None,
) -> GeminiGenAIChat:
    max_tokens = _env_int_or_none("GENAI_MAX_OUTPUT_TOKENS_CLASSIFICATION", 100)
    timeout = _env_int_or_none("GENAI_REQUEST_TIMEOUT", 60)
    return build_chat_llm(
        api_key=api_key,
        model=model,
        temperature=temperature,
        thinking_level=thinking_level,
        max_output_tokens=max_tokens,
        request_timeout=timeout,
    )


def build_extraction_llm(
    *,
    api_key: str,
    model: str,
    temperature: float,
    thinking_level: Optional[str] = None,
) -> GeminiGenAIChat:
    max_tokens = _env_int_or_none("GENAI_MAX_OUTPUT_TOKENS_EXTRACTION", 1200)
    timeout = _env_int_or_none("GENAI_REQUEST_TIMEOUT", 60)
    return build_chat_llm(
        api_key=api_key,
        model=model,
        temperature=temperature,
        thinking_level=thinking_level,
        max_output_tokens=max_tokens,
        request_timeout=timeout,
    )


def chain_prompt(prompt: Any, llm: GeminiGenAIChat) -> GeminiPromptChain:
    return GeminiPromptChain(prompt, llm)


def env_thinking_level(default: Optional[str] = None) -> Optional[str]:
    val = os.getenv("LLM_THINKING_LEVEL")
    if val is None:
        return default
    val = val.strip()
    return val or default

