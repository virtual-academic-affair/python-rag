from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import AppException
from app.modules.corpus.dtos.traversal import Candidate
from app.modules.corpus.dtos.traversal import TraversalResult
from app.modules.rag.query.answering.pageindex.citation import build_sources_from_steps
from app.modules.rag.query.retrieval.retrieval_service import FAQ_CONTEXT_LIMIT
from app.modules.rag.query.retrieval.retrieval_service import RetrievalContext, RetrievalService


@pytest.mark.asyncio
async def test_retrieval_service_returns_minimal_candidate_payload():
    svc = RetrievalService.__new__(RetrievalService)
    svc._reranker = MagicMock()
    svc._reranker.rerank_files = AsyncMock(side_effect=lambda _q, candidates: candidates)

    with patch(
        "app.modules.rag.query.retrieval.retrieval_service.hydrate_agent_file_candidates",
        AsyncMock(return_value=[{
            "file_id": "file1",
            "file_name": "Quy chế",
            "doc_description": "Mô tả ngắn",
        }]),
    ):
        result = await svc._prepare_file_candidates(
            [Candidate("file", "file1")],
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
    svc._reranker.rerank_files.assert_awaited_once_with("hỏi gì đó", result)


@pytest.mark.asyncio
async def test_retrieval_service_retrieve_context_orchestrates_traversal_files_and_faqs():
    svc = RetrievalService.__new__(RetrievalService)
    svc._reranker = MagicMock()
    svc._reranker.rerank_files = AsyncMock(side_effect=lambda _q, candidates: candidates)
    svc._reranker.rerank_faqs = AsyncMock(side_effect=lambda _q, faqs, *, limit: faqs[:limit])
    traversal_result = TraversalResult(
        file_candidates=[Candidate("file", "file1")],
        supporting_faqs=[Candidate("faq", "faq1")],
        traversal_order=["topic-1"],
        prefilter={"allowed_files": 1, "allowed_faqs": 1},
    )
    faq_doc = object()

    with patch(
        "app.modules.rag.query.retrieval.retrieval_service.run_corpus_traversal_pipeline",
        AsyncMock(return_value=traversal_result),
    ) as traversal_mock, patch(
        "app.modules.rag.query.retrieval.retrieval_service.hydrate_agent_file_candidates",
        AsyncMock(return_value=[{
            "file_id": "file1",
            "file_name": "Quy chế",
            "doc_description": "Mô tả ngắn",
        }]),
    ), patch(
        "app.modules.rag.query.retrieval.retrieval_service.fetch_supporting_faqs",
        AsyncMock(return_value=[faq_doc]),
    ) as faq_mock:
        context = await svc.retrieve_context(
            "câu hỏi",
            metadata_filter={"enrollment_year": {"from_year": 2022, "to_year": 2022}},
            user_role="student",
        )

    assert isinstance(context, RetrievalContext)
    assert context.candidate_files == [{
        "file_id": "file1",
        "file_name": "Quy chế",
        "doc_description": "Mô tả ngắn",
    }]
    assert context.faq_docs == [faq_doc]
    assert context.prefilter == {"allowed_files": 1, "allowed_faqs": 1}
    assert context.traversal_order == ["topic-1"]
    traversal_mock.assert_awaited_once()
    faq_mock.assert_awaited_once_with([Candidate("faq", "faq1")], limit=20)
    svc._reranker.rerank_faqs.assert_awaited_once_with(
        "câu hỏi",
        [faq_doc],
        limit=FAQ_CONTEXT_LIMIT,
    )


@pytest.mark.asyncio
async def test_retrieval_service_traversal_failure_returns_empty_context():
    svc = RetrievalService.__new__(RetrievalService)
    svc._reranker = MagicMock()

    with patch(
        "app.modules.rag.query.retrieval.retrieval_service.run_corpus_traversal_pipeline",
        AsyncMock(side_effect=RuntimeError("down")),
    ), patch(
        "app.modules.rag.query.retrieval.retrieval_service.fetch_supporting_faqs",
        AsyncMock(return_value=[]),
    ):
        context = await svc.retrieve_context("câu hỏi")

    assert context == RetrievalContext()


@pytest.mark.asyncio
async def test_retrieval_service_app_exception_is_not_swallowed():
    svc = RetrievalService.__new__(RetrievalService)
    svc._reranker = MagicMock()

    with patch(
        "app.modules.rag.query.retrieval.retrieval_service.run_corpus_traversal_pipeline",
        AsyncMock(side_effect=AppException("bad", status_code=400)),
    ):
        with pytest.raises(AppException):
            await svc.retrieve_context("câu hỏi")


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
        "app.modules.rag.query.answering.pageindex.citation.hydrate_source_files",
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
