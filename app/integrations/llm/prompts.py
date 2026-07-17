"""Small helpers for rendering provider-neutral chat messages."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any


def render_messages(
    templates: Sequence[tuple[str, str]],
    **values: Any,
) -> list[dict[str, str]]:
    """Format system/user message templates without an orchestration framework."""
    return [
        {"role": role, "content": template.format(**values)}
        for role, template in templates
    ]
