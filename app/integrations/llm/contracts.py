"""Provider-neutral contracts used by the application LLM gateway."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable


ToolHandler = Callable[..., Awaitable[Any]]


@dataclass(frozen=True)
class LLMUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
        }


@dataclass(frozen=True)
class LLMToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class LLMResponse:
    text: str
    tool_calls: list[LLMToolCall]
    assistant_message: dict[str, Any]
    usage: LLMUsage | None = None
    finish_reason: str | None = None


@dataclass(frozen=True)
class LLMTool:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: ToolHandler

    def as_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


@dataclass(frozen=True)
class LLMToolCallDelta:
    index: int
    id: str | None = None
    name: str | None = None
    arguments_delta: str = ""


@dataclass(frozen=True)
class LLMStreamChunk:
    text_delta: str = ""
    tool_call_deltas: list[LLMToolCallDelta] = field(default_factory=list)
    usage: LLMUsage | None = None
    finish_reason: str | None = None


class LLMStreamAccumulator:
    """Accumulate OpenAI-style streaming deltas into one assistant response."""

    def __init__(self) -> None:
        self._text_parts: list[str] = []
        self._tool_calls: dict[int, dict[str, Any]] = {}
        self._usage: LLMUsage | None = None
        self._finish_reason: str | None = None

    def add(self, chunk: LLMStreamChunk) -> None:
        if chunk.text_delta:
            self._text_parts.append(chunk.text_delta)
        if chunk.usage is not None:
            self._usage = chunk.usage
        if chunk.finish_reason is not None:
            self._finish_reason = chunk.finish_reason
        for delta in chunk.tool_call_deltas:
            current = self._tool_calls.setdefault(
                delta.index,
                {"id": "", "name": "", "arguments": ""},
            )
            if delta.id:
                current["id"] = delta.id
            if delta.name:
                current["name"] = delta.name
            current["arguments"] += delta.arguments_delta or ""

    def response(self) -> LLMResponse:
        text = "".join(self._text_parts)
        tool_calls: list[LLMToolCall] = []
        raw_tool_calls: list[dict[str, Any]] = []
        for index, raw_call in sorted(self._tool_calls.items()):
            call_id = raw_call["id"] or f"tool-call-{index}"
            raw_arguments = raw_call["arguments"] or "{}"
            try:
                arguments = json.loads(raw_arguments)
            except (TypeError, ValueError):
                arguments = {}
            if not isinstance(arguments, dict):
                arguments = {}
            tool_calls.append(
                LLMToolCall(
                    id=call_id,
                    name=raw_call["name"],
                    arguments=arguments,
                )
            )
            raw_tool_calls.append({
                "id": call_id,
                "type": "function",
                "function": {
                    "name": raw_call["name"],
                    "arguments": raw_arguments,
                },
            })

        assistant_message: dict[str, Any] = {"role": "assistant", "content": text or None}
        if raw_tool_calls:
            assistant_message["tool_calls"] = raw_tool_calls
        return LLMResponse(
            text=text,
            tool_calls=tool_calls,
            assistant_message=assistant_message,
            usage=self._usage,
            finish_reason=self._finish_reason,
        )


class LLMGatewayError(RuntimeError):
    def __init__(self, message: str, *, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code

