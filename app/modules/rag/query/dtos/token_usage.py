from __future__ import annotations

from typing import Any

from app.core.base_schema import BaseSchema


class TokenUsage(BaseSchema):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    @classmethod
    def from_mapping(cls, value: dict[str, Any] | None) -> "TokenUsage | None":
        if not value:
            return None
        return cls(
            prompt_tokens=value.get("prompt_tokens", value.get("promptTokens", 0)),
            completion_tokens=value.get("completion_tokens", value.get("completionTokens", 0)),
            total_tokens=value.get("total_tokens", value.get("totalTokens", 0)),
        )
