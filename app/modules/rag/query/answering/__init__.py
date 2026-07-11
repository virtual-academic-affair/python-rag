from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.modules.rag.query.answering.pageindex import (
        BASE_PAGEINDEX_SYSTEM_PROMPT,
        CHAT_SYSTEM_PROMPT,
        EMAIL_SYSTEM_PROMPT,
        build_pageindex_system_prompt,
        run_agent_loop,
        stream_agent_loop,
    )


__all__ = [
    "BASE_PAGEINDEX_SYSTEM_PROMPT",
    "CHAT_SYSTEM_PROMPT",
    "EMAIL_SYSTEM_PROMPT",
    "build_pageindex_system_prompt",
    "run_agent_loop",
    "stream_agent_loop",
]


def __getattr__(name: str) -> Any:
    if name in {
        "BASE_PAGEINDEX_SYSTEM_PROMPT",
        "CHAT_SYSTEM_PROMPT",
        "EMAIL_SYSTEM_PROMPT",
        "build_pageindex_system_prompt",
        "run_agent_loop",
        "stream_agent_loop",
    }:
        from app.modules.rag.query.answering.pageindex import (
            BASE_PAGEINDEX_SYSTEM_PROMPT,
            CHAT_SYSTEM_PROMPT,
            EMAIL_SYSTEM_PROMPT,
            build_pageindex_system_prompt,
            run_agent_loop,
            stream_agent_loop,
        )

        return {
            "BASE_PAGEINDEX_SYSTEM_PROMPT": BASE_PAGEINDEX_SYSTEM_PROMPT,
            "CHAT_SYSTEM_PROMPT": CHAT_SYSTEM_PROMPT,
            "EMAIL_SYSTEM_PROMPT": EMAIL_SYSTEM_PROMPT,
            "build_pageindex_system_prompt": build_pageindex_system_prompt,
            "run_agent_loop": run_agent_loop,
            "stream_agent_loop": stream_agent_loop,
        }[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
