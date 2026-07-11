from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.corpus.dtos.traversal import Candidate, TraversalResult
from app.modules.rag.query.retrieval.traversal.pipeline import run_corpus_traversal_pipeline


@pytest.mark.asyncio
async def test_traversal_pipeline_prefilter_resolves_without_relaxing_years():
    corpus_svc = MagicMock()
    corpus_svc.repo = MagicMock()
    corpus_svc.fetch_allowed_ids = AsyncMock(return_value=({"file-1"}, {"faq-1"}))
    corpus_svc.resolve_candidates = AsyncMock(return_value=TraversalResult(
        file_candidates=[Candidate("file", "file-1")],
        supporting_faqs=[Candidate("faq", "faq-1")],
        traversal_order=["topic-1"],
    ))

    with patch(
        "app.modules.rag.query.retrieval.traversal.pipeline.get_corpus_service",
        return_value=corpus_svc,
    ), patch(
        "app.modules.rag.query.retrieval.traversal.pipeline.run_corpus_traversal",
        AsyncMock(return_value=(["topic-1"], ["topic-1"])),
    ) as traversal_mock:
        result = await run_corpus_traversal_pipeline(
            "Câu hỏi",
            metadata_filter={"enrollment_year": {"from_year": 2022, "to_year": 2022}},
            user_role="student",
        )

    assert result.prefilter == {
        "allowed_files": 1,
        "allowed_faqs": 1,
    }
    traversal_mock.assert_awaited_once_with(
        "Câu hỏi",
        corpus_svc.repo,
        {"file-1"},
        {"faq-1"},
    )
    corpus_svc.resolve_candidates.assert_awaited_once_with(
        ["topic-1"],
        {"file-1"},
        {"faq-1"},
        traversal_order=["topic-1"],
    )


@pytest.mark.asyncio
async def test_traversal_pipeline_returns_empty_when_prefilter_has_no_matches():
    corpus_svc = MagicMock()
    corpus_svc.repo = MagicMock()
    corpus_svc.fetch_allowed_ids = AsyncMock(return_value=(set(), set()))

    with patch(
        "app.modules.rag.query.retrieval.traversal.pipeline.get_corpus_service",
        return_value=corpus_svc,
    ), patch(
        "app.modules.rag.query.retrieval.traversal.pipeline.run_corpus_traversal",
        AsyncMock(),
    ) as traversal_mock:
        result = await run_corpus_traversal_pipeline(
            "Câu hỏi",
            metadata_filter={"enrollment_year": {"from_year": 2022, "to_year": 2022}},
            user_role="student",
        )

    assert result.prefilter == {"allowed_files": 0, "allowed_faqs": 0}
    assert result.file_candidates == []
    assert result.supporting_faqs == []
    traversal_mock.assert_not_awaited()
