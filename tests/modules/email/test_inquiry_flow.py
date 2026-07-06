"""Inquiry email flow giống chat: corpus traversal → FAQ fast-path → agent loop.

Test _run_rag_pipeline (phần RAG tách riêng) với các collaborator được mock,
kiểm tra: traversal chạy với role=student + metadata_filter, FAQ fast-path
short-circuit trước agent loop, và fallback bypass khi rỗng.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.modules.email.workflows.inquiry_service import InquiryService
from app.modules.rag.corpus.dtos.traversal import Candidate, TraversalResult

MF = {"enrollment_year": {"from_year": 2022, "to_year": 2022}}


def _svc(enrich_return):
    svc = InquiryService.__new__(InquiryService)  # bỏ qua __init__ (build LLM thật)
    svc._retrieval = MagicMock()
    svc._retrieval.enrich_corpus_candidates = AsyncMock(return_value=enrich_return)
    return svc


def _patch_traversal(traversal_result):
    """Patch get_corpus_traversal_service → svc.traverse trả traversal_result.
    Trả về (patcher, traverse_mock) để assert call args."""
    traverse_mock = AsyncMock(return_value=traversal_result)
    fake_svc = SimpleNamespace(traverse=traverse_mock)
    patcher = patch(
        "app.modules.email.workflows.inquiry_service.get_corpus_traversal_service",
        return_value=fake_svc,
    )
    return patcher, traverse_mock


async def test_faq_fast_path_short_circuits_agent_loop():
    """FAQ fast-path đủ thông tin → source=faq, KHÔNG chạy agent loop."""
    svc = _svc(enrich_return=[{"file_id": "f1", "file_name": "Doc", "doc_description": ""}])
    result = TraversalResult(
        file_candidates=[Candidate("file", "f1")],
        supporting_faqs=[Candidate("faq", "q1")],
    )
    patcher, traverse_mock = _patch_traversal(result)

    with patcher, \
        patch("app.modules.email.workflows.inquiry_service.fetch_supporting_faqs",
              AsyncMock(return_value=[object()])), \
        patch("app.modules.email.workflows.inquiry_service.try_faq_fast_path",
              AsyncMock(return_value="Trả lời từ FAQ")) as fast_path, \
        patch("app.modules.email.workflows.inquiry_service.run_agent_loop",
              AsyncMock()) as agent_loop:
        out = await svc._run_rag_pipeline("Chuẩn ngoại ngữ K22?", "Tiêu đề", "Nội dung", MF)

    assert out == {"answer": "Trả lời từ FAQ", "sources": [], "source": "faq"}
    fast_path.assert_awaited_once()
    agent_loop.assert_not_awaited()
    # Traversal chạy với role student + metadata_filter của email
    traverse_mock.assert_awaited_once()
    _, kwargs = traverse_mock.call_args
    assert kwargs["user_role"] == "student"
    assert kwargs["metadata_filter"] == MF


async def test_agent_loop_when_faq_insufficient():
    """FAQ không đủ → chạy agent loop với faq_context nhồi vào prompt, source=llm."""
    svc = _svc(enrich_return=[{"file_id": "f1", "file_name": "Quy chế", "doc_description": "Mô tả"}])
    result = TraversalResult(
        file_candidates=[Candidate("file", "f1")],
        supporting_faqs=[Candidate("faq", "q1")],
    )
    patcher, _ = _patch_traversal(result)

    agent_mock = AsyncMock(return_value={"final_answer": "Câu trả lời tài liệu", "sources": [{"citationId": 1}]})
    with patcher, \
        patch("app.modules.email.workflows.inquiry_service.fetch_supporting_faqs",
              AsyncMock(return_value=[object()])), \
        patch("app.modules.email.workflows.inquiry_service.build_faq_context",
              return_value="## FAQ context\n\n"), \
        patch("app.modules.email.workflows.inquiry_service.try_faq_fast_path",
              AsyncMock(return_value=None)), \
        patch("app.modules.email.workflows.inquiry_service.run_agent_loop", agent_mock):
        out = await svc._run_rag_pipeline("Câu hỏi", "Tiêu đề", "Nội dung email", MF)

    assert out["source"] == "llm"
    assert out["answer"] == "Câu trả lời tài liệu"
    assert out["sources"] == [{"citationId": 1}]
    # faq_context được nhồi vào prompt của agent
    _, kwargs = agent_mock.call_args
    assert "## FAQ context" in kwargs["prompt_contents"]
    assert kwargs["citation_link_type"] == "original"


async def test_bypass_when_no_files_and_no_faq():
    """Không file, FAQ fast-path None → source=bypass."""
    svc = _svc(enrich_return=[])
    patcher, _ = _patch_traversal(TraversalResult())

    with patcher, \
        patch("app.modules.email.workflows.inquiry_service.fetch_supporting_faqs",
              AsyncMock(return_value=[])), \
        patch("app.modules.email.workflows.inquiry_service.try_faq_fast_path",
              AsyncMock(return_value=None)), \
        patch("app.modules.email.workflows.inquiry_service.run_agent_loop",
              AsyncMock()) as agent_loop:
        out = await svc._run_rag_pipeline("Câu hỏi", "Tiêu đề", "Nội dung", {})

    assert out["source"] == "bypass"
    assert out["sources"] == []
    agent_loop.assert_not_awaited()


async def test_traversal_failure_falls_back_to_bypass():
    """traverse raise → best-effort empty result → bypass (không vỡ luồng email)."""
    svc = _svc(enrich_return=[])
    traverse_mock = AsyncMock(side_effect=RuntimeError("corpus down"))
    fake_svc = SimpleNamespace(traverse=traverse_mock)

    with patch("app.modules.email.workflows.inquiry_service.get_corpus_traversal_service",
               return_value=fake_svc), \
        patch("app.modules.email.workflows.inquiry_service.fetch_supporting_faqs",
              AsyncMock(return_value=[])), \
        patch("app.modules.email.workflows.inquiry_service.try_faq_fast_path",
              AsyncMock(return_value=None)):
        out = await svc._run_rag_pipeline("Câu hỏi", "Tiêu đề", "Nội dung", MF)

    assert out["source"] == "bypass"
