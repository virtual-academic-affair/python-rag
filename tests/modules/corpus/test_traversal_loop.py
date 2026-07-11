from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from google.genai import types

from app.core.exceptions import CorpusTraversalError
from app.modules.corpus.models.corpus_node import CorpusNodeDocument
from app.modules.rag.query.retrieval.traversal.loop import run_corpus_traversal


def _make_node(node_key, file_ids=None, faq_ids=None, child_keys=None, parent_key=None):
    node = MagicMock(spec=CorpusNodeDocument)
    node.node_key = node_key
    node.title = node_key
    node.summary = ""
    node.direct_file_ids = file_ids or []
    node.direct_faq_ids = faq_ids or []
    node.subtree_file_ids = file_ids or []
    node.subtree_faq_ids = faq_ids or []
    node.child_keys = child_keys or []
    node.parent_key = parent_key
    return node


def _tool_call_response(name: str, args: dict):
    part = types.Part.from_function_call(name=name, args=args)
    content = types.Content(role="model", parts=[part])
    return SimpleNamespace(candidates=[SimpleNamespace(content=content)])


@pytest.mark.asyncio
async def test_run_corpus_traversal_validates_select_topics():
    valid = _make_node("valid-topic", file_ids=["file-ok"])
    blocked = _make_node("blocked-topic", file_ids=["file-blocked"])
    repo = MagicMock()
    repo.get_all = AsyncMock(return_value=[valid, blocked])

    with patch(
        "app.modules.rag.query.retrieval.traversal.loop.async_retry",
        AsyncMock(return_value=_tool_call_response(
            "select_topics",
            {"node_keys": ["valid-topic", "missing-topic", "blocked-topic"]},
        )),
    ):
        selected, expand_stack = await run_corpus_traversal(
            "Câu hỏi",
            repo,
            allowed_files={"file-ok"},
            allowed_faqs=set(),
        )

    assert selected == ["valid-topic"]
    assert expand_stack == []


@pytest.mark.asyncio
async def test_run_corpus_traversal_llm_failure_raises_app_exception():
    repo = MagicMock()

    with patch(
        "app.modules.rag.query.retrieval.traversal.loop.async_retry",
        AsyncMock(side_effect=RuntimeError("gemini down")),
    ):
        with pytest.raises(CorpusTraversalError) as exc:
            await run_corpus_traversal(
                "Câu hỏi",
                repo,
                allowed_files={"file-ok"},
                allowed_faqs=set(),
            )

    assert exc.value.status_code == 502
