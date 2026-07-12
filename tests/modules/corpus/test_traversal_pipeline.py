from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.corpus.contracts import FileCandidate, TraversalResult
from app.modules.rag.query.retrieval.traversal.pipeline import run_corpus_traversal_pipeline
from app.modules.rag.query.retrieval.traversal.runtime.snapshot import build_filtered_snapshot_from_nodes


@pytest.mark.asyncio
async def test_traversal_pipeline_keeps_agent_candidates_without_recursive_resolution():
    corpus_svc = MagicMock()
    corpus_svc.repo = MagicMock()
    snapshot = build_filtered_snapshot_from_nodes([], {"file-1"}, {"faq-1"})
    traversal_result = TraversalResult(status="selected", file_candidates=[FileCandidate("file-1")])
    with patch("app.modules.rag.query.retrieval.traversal.pipeline.get_corpus_service", return_value=corpus_svc), patch(
        "app.modules.rag.query.retrieval.traversal.pipeline.build_filtered_snapshot",
        AsyncMock(return_value=snapshot),
    ) as snapshot_mock, patch(
        "app.modules.rag.query.retrieval.traversal.pipeline.run_corpus_traversal",
        AsyncMock(return_value=traversal_result),
    ) as traversal_mock:
        result = await run_corpus_traversal_pipeline("Câu hỏi", user_role="student")

    assert result.prefilter == {"allowed_file_count": 1, "allowed_faq_count": 1}
    assert result.file_candidates == [FileCandidate("file-1")]
    snapshot_mock.assert_awaited_once_with(
        corpus_svc.repo,
        corpus_svc,
        metadata_filter=None,
        user_role="student",
        trace_id="",
    )
    traversal_mock.assert_awaited_once_with("Câu hỏi", snapshot, trace_id="")


@pytest.mark.asyncio
async def test_traversal_pipeline_returns_explicit_no_match_when_prefilter_empty():
    corpus_svc = MagicMock()
    snapshot = build_filtered_snapshot_from_nodes([], set(), set())
    with patch("app.modules.rag.query.retrieval.traversal.pipeline.get_corpus_service", return_value=corpus_svc), patch(
        "app.modules.rag.query.retrieval.traversal.pipeline.build_filtered_snapshot",
        AsyncMock(return_value=snapshot),
    ), patch(
        "app.modules.rag.query.retrieval.traversal.pipeline.run_corpus_traversal", AsyncMock()
    ) as traversal_mock:
        result = await run_corpus_traversal_pipeline("Câu hỏi", user_role="student")

    assert result.status == "no_match"
    assert result.termination_reason == "prefilter_empty"
    traversal_mock.assert_not_awaited()
