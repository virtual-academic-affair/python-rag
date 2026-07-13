from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.core.exceptions import ConflictException
from app.modules.corpus.contracts import FaqCandidate, FileCandidate, TraversalResult
from app.modules.corpus.dtos import CorpusTraversalRequest
from app.modules.corpus.services.corpus_debug_service import CorpusDebugService
from app.modules.corpus.services.corpus_job_service import CorpusJobService
from app.modules.corpus.routers.corpus_router import corpus_tree


@pytest.mark.asyncio
async def test_corpus_job_service_rejects_duplicate_backfill():
    corpus_service = SimpleNamespace(backfill_corpus=AsyncMock())
    svc = CorpusJobService(corpus_service=corpus_service)
    svc._backfill_running = True

    with pytest.raises(ConflictException):
        await svc.trigger_backfill()


@pytest.mark.asyncio
async def test_corpus_tree_maps_public_query_filters_to_service_contract():
    corpus_service = SimpleNamespace(build_tree=AsyncMock(return_value=SimpleNamespace(tree=[])))
    with patch(
        "app.modules.corpus.routers.corpus_router.get_corpus_service",
        return_value=corpus_service,
    ):
        await corpus_tree(
            metadata_filter='{"enrollmentYear":{"fromYear":2022,"toYear":2022},"academicYear":{"fromYear":2024,"toYear":2024}}',
            lecturer_only=False,
            _admin=SimpleNamespace(),
        )

    corpus_service.build_tree.assert_awaited_once_with(
        metadata_filter={
            "enrollment_year": {"from_year": 2022, "to_year": 2022},
            "academic_year": {"from_year": 2024, "to_year": 2024},
        },
        lecturer_only=False,
    )


@pytest.mark.asyncio
async def test_corpus_tree_rejects_invalid_metadata_filter_json():
    with pytest.raises(Exception, match="Invalid metadataFilter JSON"):
        await corpus_tree(metadata_filter="{bad-json", lecturer_only=None, _admin=SimpleNamespace())


@pytest.mark.asyncio
async def test_corpus_debug_service_traverse_maps_result():
    traversal = TraversalResult(
        file_candidates=[FileCandidate(file_id="file-1", node_key="node-1", node_title="Node")],
        faq_candidates=[FaqCandidate(faq_id="faq-1", node_key="node-1", node_title="Node")],
        expanded_node_keys=["node-1"],
        prefilter={"allowed_file_count": 1, "allowed_faq_count": 1},
    )
    svc = CorpusDebugService()

    with patch(
        "app.modules.corpus.services.corpus_debug_service.run_corpus_traversal_pipeline",
        AsyncMock(return_value=traversal),
    ):
        response = await svc.traverse(CorpusTraversalRequest(question="q", role="student"))

    assert response.expanded_node_keys == ["node-1"]
    assert response.file_candidates[0].file_id == "file-1"
    assert response.faq_candidates[0].faq_id == "faq-1"
    assert response.prefilter.allowed_file_count == 1


@pytest.mark.asyncio
async def test_rag_debug_service_chat_preview_uses_shared_pipeline():
    rag_result = SimpleNamespace(
        analysis=None,
        answer_markdown="FAQ answer",
        candidate_files=[{"file_id": "file-1", "file_name": "Quy chế"}],
        faq_docs=[SimpleNamespace(id="faq-1", question="FAQ?")],
        steps=[],
        sources=[],
        source="faq",
        max_turns_reached=False,
        is_direct_reply=False,
        token_usage=None,
    )
    pipeline = SimpleNamespace(answer_chat=AsyncMock(return_value=rag_result))
    from app.modules.rag.query.debug_service import RagDebugService
    from app.modules.rag.query.dtos import RagChatPreviewRequest
    svc = RagDebugService()

    with patch(
        "app.modules.rag.query.debug_service.get_rag_query_pipeline",
        return_value=pipeline,
    ):
        response = await svc.chat_preview(RagChatPreviewRequest(question="q", role="student"))

    pipeline.answer_chat.assert_awaited_once()
    assert response.source == "faq"
    assert response.answer == "FAQ answer"
    assert response.file_candidates[0].file_id == "file-1"
