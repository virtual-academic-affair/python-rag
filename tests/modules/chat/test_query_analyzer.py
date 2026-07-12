import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.modules.chat.dtos import ChatHistoryItem
from app.modules.rag.query.analyzer.chat_query_analyzer_service import ChatQueryAnalyzer


def _history(count: int = 8):
    return [
        ChatHistoryItem(role="user" if i % 2 == 0 else "assistant", content=f"message-{i}")
        for i in range(count)
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("raw_value", "expected"),
    [
        (False, False),
        (True, True),
        ("false", False),
        ("TRUE", True),
        ("invalid", True),
    ],
)
async def test_analyze_query_normalizes_needs_rag(raw_value, expected):
    analyzer = ChatQueryAnalyzer()
    retry_mock = AsyncMock(return_value=SimpleNamespace(
        text=json.dumps({"needs_rag": raw_value, "effective_question": "q", "metadata_filter": None}),
        usage_metadata=None,
    ))

    with patch("app.modules.rag.query.analyzer.chat_query_analyzer_service.async_retry", retry_mock), \
        patch("app.modules.rag.query.analyzer.chat_query_analyzer_service.extract_metadata_from_text", AsyncMock(return_value=None)):
        result = await analyzer.analyze_query("q", [])

    assert result.needs_rag is expected


@pytest.mark.asyncio
async def test_analyzer_prompts_only_use_last_six_history_items():
    analyzer = ChatQueryAnalyzer()
    retry_mock = AsyncMock(return_value=SimpleNamespace(
        text='{"needs_rag": true, "effective_question": "q", "metadata_filter": null}',
        usage_metadata=None,
    ))

    with patch("app.modules.rag.query.analyzer.chat_query_analyzer_service.async_retry", retry_mock), \
        patch("app.modules.rag.query.analyzer.chat_query_analyzer_service.extract_metadata_from_text", AsyncMock(return_value=None)):
        await analyzer.analyze_query("q", _history())

    prompt = retry_mock.call_args.kwargs["contents"][0]
    assert "message-0" not in prompt
    assert "message-1" not in prompt
    assert "message-2" in prompt
    assert "message-7" in prompt


@pytest.mark.asyncio
async def test_direct_reply_prompt_only_uses_last_six_history_items():
    analyzer = ChatQueryAnalyzer()
    retry_mock = AsyncMock(return_value=SimpleNamespace(text="ok", usage_metadata=None))

    with patch("app.modules.rag.query.analyzer.chat_query_analyzer_service.async_retry", retry_mock):
        answer, _usage = await analyzer.generate_reply("q", _history())

    prompt = retry_mock.call_args.kwargs["contents"][0]
    assert answer == "ok"
    assert "message-0" not in prompt
    assert "message-1" not in prompt
    assert "message-2" in prompt
    assert "message-7" in prompt
