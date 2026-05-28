"""
Unified LLM Factory and Gemini Client.
Provides a singleton Gemini client for Chat/Email and a factory for chain/orchestration models.
"""

import asyncio
import logging
from typing import Any, Dict, Optional
from google import genai
from google.genai import types
from langchain_core.prompts import ChatPromptTemplate

from app.core.config import settings

logger = logging.getLogger(__name__)

class GeminiClient:
    """
    Singleton service for Gemini API client initialization.
    """
    
    _instance: Optional["GeminiClient"] = None
    _client: Optional[genai.Client] = None
    
    def __new__(cls):
        """Singleton pattern implementation."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        """Initialize Gemini client (only once)."""
        if self._client is None:
            self._client = genai.Client(api_key=settings.GOOGLE_API_KEY)
    
    @property
    def client(self) -> genai.Client:
        """Get the Gemini client instance for synchronous operations."""
        if self._client is None:
            raise RuntimeError("Gemini client not initialized")
        return self._client

gemini_client = GeminiClient()

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
        request_timeout: Optional[int] = None,
    ):
        self._client = genai.Client(api_key=api_key)
        self._model = model
        self._temperature = temperature
        self._thinking_level = thinking_level
        self._request_timeout = request_timeout or settings.GENAI_REQUEST_TIMEOUT

    def _build_config(self) -> types.GenerateContentConfig:
        kwargs: Dict[str, Any] = {}
        if self._temperature is not None:
            kwargs["temperature"] = self._temperature
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
        if model_name:
            # Strip litellm-style provider prefix if present
            if model_name.startswith("gemini/"):
                model_name = model_name.replace("gemini/", "")
            
            if not model_name.startswith("models/"):
                model_name = f"models/{model_name}"

        resp = await self._client.aio.models.generate_content(
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
    request_timeout: Optional[int] = None,
) -> GeminiGenAIChat:
    logger.info(
        "Building google-genai client model=%s temperature=%s thinking=%s timeout=%s",
        model,
        temperature,
        thinking_level,
        request_timeout,
    )
    return GeminiGenAIChat(
        api_key=api_key,
        model=model,
        temperature=temperature,
        thinking_level=thinking_level,
        request_timeout=request_timeout,
    )


def build_classification_llm(
    *,
    api_key: str,
    model: str,
    temperature: float,
    thinking_level: Optional[str] = None,
) -> GeminiGenAIChat:
    return build_chat_llm(
        api_key=api_key,
        model=model,
        temperature=temperature,
        thinking_level=thinking_level,
        request_timeout=settings.GENAI_REQUEST_TIMEOUT,
    )


def build_extraction_llm(
    *,
    api_key: str,
    model: str,
    temperature: float,
    thinking_level: Optional[str] = None,
) -> GeminiGenAIChat:
    return build_chat_llm(
        api_key=api_key,
        model=model,
        temperature=temperature,
        thinking_level=thinking_level,
        request_timeout=settings.GENAI_REQUEST_TIMEOUT,
    )


def chain_prompt(prompt: Any, llm: GeminiGenAIChat) -> GeminiPromptChain:
    return GeminiPromptChain(prompt, llm)


def env_thinking_level(default: Optional[str] = None) -> Optional[str]:
    val = settings.LLM_THINKING_LEVEL
    return val or default
