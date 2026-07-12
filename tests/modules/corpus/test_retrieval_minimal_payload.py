from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import AppException
from app.modules.corpus.contracts import FaqCandidate, FileCandidate, TraversalResult
from app.modules.rag.query.answering.pageindex_agent.citations.source_builder import build_sources_from_steps
from app.modules.rag.query.retrieval.retrieval_service import FAQ_CONTEXT_LIMIT
from app.modules.rag.query.retrieval.retrieval_service import RetrievalService


@pytest.mark.asyncio
async def test_retrieval_service_returns_minimal_candidate_payload():
    svc = RetrievalService.__new__(RetrievalService)
    svc._reranker = MagicMock()
    svc._reranker.rerank_files = AsyncMock(side_effect=lambda _q, candidates, *, limit: candidates)

    with patch(
        "app.modules.rag.query.retrieval.retrieval_service.hydrate_pageindex_candidate_files",
        AsyncMock(return_value=[{
            "file_id": "file1",
            "file_name": "Quy chế",
            "doc_description": "Mô tả ngắn",
        }]),
    ):
        result = await svc._prepare_file_candidates(
            [FileCandidate("file1")],
            question="hỏi gì đó",
        )

    assert result == [{
        "file_id": "file1",
        "file_name": "Quy chế",
        "doc_description": "Mô tả ngắn",
    }]
    assert "structure" not in result[0]
    assert "table_of_contents" not in result[0]
    assert "storage_path" not in result[0]
    assert "markdown_storage_path" not in result[0]
    svc._reranker.rerank_files.assert_awaited_once_with("hỏi gì đó", result, limit=5)


@pytest.mark.asyncio
async def test_retrieval_service_traverse_and_faq_context_are_separate():
    svc = RetrievalService.__new__(RetrievalService)
    svc._reranker = MagicMock()
    svc._reranker.rerank_faqs = AsyncMock(side_effect=lambda _q, faqs, *, limit: faqs[:limit])
    traversal_result = TraversalResult(
        file_candidates=[FileCandidate("file1")],
        faq_candidates=[FaqCandidate("faq1")],
        traversal_node_keys=["topic-1"],
        prefilter={"allowed_file_count": 1, "allowed_faq_count": 1},
    )
    faq_doc = object()

    with patch(
        "app.modules.rag.query.retrieval.retrieval_service.run_corpus_traversal_pipeline",
        AsyncMock(return_value=traversal_result),
    ) as traversal_mock:
        seeds = await svc.traverse_query(
            "câu hỏi",
            metadata_filter={"enrollment_year": {"from_year": 2022, "to_year": 2022}},
            user_role="student",
        )

    with patch(
        "app.modules.rag.query.retrieval.retrieval_service.hydrate_faq_candidate_docs",
        AsyncMock(return_value=[faq_doc]),
    ) as faq_mock:
        faq_docs = await svc.retrieve_faq_context("câu hỏi", seeds.faq_candidates)

    assert seeds.file_candidates == [FileCandidate("file1")]
    assert seeds.faq_candidates == [FaqCandidate("faq1")]
    assert seeds.prefilter == {"allowed_file_count": 1, "allowed_faq_count": 1}
    assert seeds.traversal_node_keys == ["topic-1"]
    assert faq_docs == [faq_doc]
    traversal_mock.assert_awaited_once()
    faq_mock.assert_awaited_once_with([FaqCandidate("faq1")], limit=1000)
    svc._reranker.rerank_faqs.assert_awaited_once_with(
        "câu hỏi",
        [faq_doc],
        limit=FAQ_CONTEXT_LIMIT,
    )


@pytest.mark.asyncio
async def test_retrieval_service_traversal_failure_is_not_swallowed():
    svc = RetrievalService.__new__(RetrievalService)
    svc._reranker = MagicMock()

    with patch(
        "app.modules.rag.query.retrieval.retrieval_service.run_corpus_traversal_pipeline",
        AsyncMock(side_effect=RuntimeError("down")),
    ):
        with pytest.raises(RuntimeError):
            await svc.traverse_query("câu hỏi")


@pytest.mark.asyncio
async def test_retrieval_service_app_exception_is_not_swallowed():
    svc = RetrievalService.__new__(RetrievalService)
    svc._reranker = MagicMock()

    with patch(
        "app.modules.rag.query.retrieval.retrieval_service.run_corpus_traversal_pipeline",
        AsyncMock(side_effect=AppException("bad", status_code=400)),
    ):
        with pytest.raises(AppException):
            await svc.traverse_query("câu hỏi")


@pytest.mark.asyncio
async def test_build_sources_from_minimal_candidates_hydrates_accessed_file():
    steps = [
        {"type": "call", "name": "get_page_content", "args": {"file_id": "1", "pages": "10-12"}},
    ]
    candidate_files = [{
        "file_id": "file1",
        "file_name": "Quy chế",
        "doc_description": "Mô tả ngắn",
    }]

    with patch(
        "app.modules.rag.query.answering.pageindex_agent.citations.source_builder.hydrate_source_files",
        AsyncMock(return_value={
            "file1": {
                "file_id": "file1",
                "file_name": "Quy chế",
                "original_url": "https://example.test/original.pdf",
                "markdown_url": "https://example.test/file.md",
                "structure": [{"title": "Mục cần đọc", "line_num": 8, "nodes": []}],
                "table_of_contents": ["Mục cần đọc"],
            }
        }),
    ):
        sources = await build_sources_from_steps(steps, candidate_files)

    assert len(sources) == 1
    assert sources[0]["file_id"] == "file1"
    assert sources[0]["titles"] == ["Mục cần đọc"]
    assert sources[0]["original_url"] == "https://example.test/original.pdf"
    assert sources[0]["markdown_url"] == "https://example.test/file.md"
    assert sources[0]["table_of_contents"] == ["Mục cần đọc"]
