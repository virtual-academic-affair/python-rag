"""In-process LLM gateway backed by the LiteLLM Python SDK."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator
from typing import Any

import litellm

from app.core.config import settings
from app.integrations.llm.contracts import (
    LLMGatewayError,
    LLMResponse,
    LLMStreamChunk,
    LLMTool,
    LLMToolCall,
    LLMToolCallDelta,
    LLMUsage,
)
from app.utils.retry import async_retry

logger = logging.getLogger(__name__)


_RETRYABLE_EXCEPTIONS = (
    litellm.RateLimitError,
    litellm.APIConnectionError,
    litellm.Timeout,
    litellm.ServiceUnavailableError,
    litellm.InternalServerError,
)


def _value(obj: Any, key: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _usage(raw_usage: Any) -> LLMUsage | None:
    if raw_usage is None:
        return None
    prompt_tokens = int(_value(raw_usage, "prompt_tokens", 0) or 0)
    completion_tokens = int(_value(raw_usage, "completion_tokens", 0) or 0)
    total_tokens = int(
        _value(raw_usage, "total_tokens", prompt_tokens + completion_tokens)
        or prompt_tokens + completion_tokens
    )
    return LLMUsage(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
    )


def _status_code(exc: Exception) -> int:
    status_code = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    return status_code if isinstance(status_code, int) else 502


class LLMGateway:
    """Expose one provider-neutral completion contract to application modules."""

    def __init__(self, completion_fn: Any = None):
        self._completion_fn = completion_fn or litellm.acompletion

    def _request_kwargs(
        self,
        *,
        messages: list[dict[str, Any]],
        model: str | None,
        temperature: float | None,
        response_format: dict[str, Any] | None,
        tools: list[LLMTool] | None,
        stream: bool,
    ) -> dict[str, Any]:
        resolved_model = model or settings.LLM_MODEL
        kwargs: dict[str, Any] = {
            "model": resolved_model,
            "messages": messages,
            "api_key": settings.LLM_API_KEY,
            "timeout": settings.LLM_TIMEOUT_SECONDS,
            "num_retries": 0,
            "stream": stream,
        }
        if temperature is not None:
            kwargs["temperature"] = temperature
        if response_format is not None:
            kwargs["response_format"] = response_format
        if tools:
            kwargs["tools"] = [tool.as_schema() for tool in tools]
            kwargs["tool_choice"] = "auto"
        if stream:
            kwargs["stream_options"] = {"include_usage": True}
        return kwargs

    async def _request(self, **kwargs: Any) -> Any:
        try:
            return await async_retry(
                self._completion_fn,
                max_attempts=settings.LLM_MAX_ATTEMPTS,
                retryable_exceptions=_RETRYABLE_EXCEPTIONS,
                **kwargs,
            )
        except Exception as exc:
            raise LLMGatewayError(str(exc), status_code=_status_code(exc)) from exc

    async def complete(
        self,
        *,
        messages: list[dict[str, Any]],
        model: str | None = None,
        temperature: float | None = None,
        response_format: dict[str, Any] | None = None,
        tools: list[LLMTool] | None = None,
    ) -> LLMResponse:
        response = await self._request(**self._request_kwargs(
            messages=messages,
            model=model,
            temperature=temperature,
            response_format=response_format,
            tools=tools,
            stream=False,
        ))
        choices = _value(response, "choices", []) or []
        if not choices:
            return LLMResponse(text="", tool_calls=[], assistant_message={"role": "assistant", "content": ""}, usage=_usage(_value(response, "usage")))

        choice = choices[0]
        message = _value(choice, "message", {})
        text = _value(message, "content", "") or ""
        raw_tool_calls = _value(message, "tool_calls", []) or []
        tool_calls: list[LLMToolCall] = []
        normalized_raw_calls: list[dict[str, Any]] = []
        for index, raw_call in enumerate(raw_tool_calls):
            function = _value(raw_call, "function", {})
            raw_arguments = _value(function, "arguments", "{}") or "{}"
            if isinstance(raw_arguments, dict):
                arguments = raw_arguments
                raw_arguments = json.dumps(raw_arguments, ensure_ascii=False)
            else:
                try:
                    arguments = json.loads(raw_arguments)
                except (TypeError, ValueError):
                    arguments = {}
            if not isinstance(arguments, dict):
                arguments = {}
            call_id = _value(raw_call, "id", None) or f"tool-call-{index}"
            name = _value(function, "name", "") or ""
            tool_calls.append(LLMToolCall(id=call_id, name=name, arguments=arguments))
            normalized_raw_calls.append({
                "id": call_id,
                "type": "function",
                "function": {"name": name, "arguments": raw_arguments},
            })

        assistant_message: dict[str, Any] = {"role": "assistant", "content": text or None}
        if normalized_raw_calls:
            assistant_message["tool_calls"] = normalized_raw_calls
        return LLMResponse(
            text=text,
            tool_calls=tool_calls,
            assistant_message=assistant_message,
            usage=_usage(_value(response, "usage")),
            finish_reason=_value(choice, "finish_reason"),
        )

    async def stream(
        self,
        *,
        messages: list[dict[str, Any]],
        model: str | None = None,
        temperature: float | None = None,
        tools: list[LLMTool] | None = None,
    ) -> AsyncGenerator[LLMStreamChunk, None]:
        stream = await self._request(**self._request_kwargs(
            messages=messages,
            model=model,
            temperature=temperature,
            response_format=None,
            tools=tools,
            stream=True,
        ))
        try:
            async for raw_chunk in stream:
                choices = _value(raw_chunk, "choices", []) or []
                raw_usage = _usage(_value(raw_chunk, "usage"))
                if not choices:
                    if raw_usage is not None:
                        yield LLMStreamChunk(usage=raw_usage)
                    continue
                choice = choices[0]
                delta = _value(choice, "delta", {})
                tool_deltas = []
                for raw_call in _value(delta, "tool_calls", []) or []:
                    function = _value(raw_call, "function", {})
                    tool_deltas.append(LLMToolCallDelta(
                        index=int(_value(raw_call, "index", 0) or 0),
                        id=_value(raw_call, "id"),
                        name=_value(function, "name"),
                        arguments_delta=_value(function, "arguments", "") or "",
                    ))
                yield LLMStreamChunk(
                    text_delta=_value(delta, "content", "") or "",
                    tool_call_deltas=tool_deltas,
                    usage=raw_usage,
                    finish_reason=_value(choice, "finish_reason"),
                )
        except LLMGatewayError:
            raise
        except Exception as exc:
            raise LLMGatewayError(str(exc), status_code=_status_code(exc)) from exc
        finally:
            close_stream = getattr(stream, "aclose", None)
            if close_stream is not None:
                try:
                    await close_stream()
                except Exception as exc:
                    logger.warning("Failed to close LiteLLM response stream: %s", exc)


_gateway: LLMGateway | None = None


def get_llm_gateway() -> LLMGateway:
    global _gateway
    if _gateway is None:
        _gateway = LLMGateway()
    return _gateway


async def close_llm_clients() -> None:
    """Close LiteLLM's cached async HTTP clients on application shutdown."""
    await litellm.close_litellm_async_clients()
