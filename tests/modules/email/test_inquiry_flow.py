"""Inquiry email flow: mock only the shared RAG pipeline."""
from unittest.mock import AsyncMock, MagicMock, patch

from app.modules.email.workflows.inquiry_service import InquiryService
from app.modules.rag.query import RagQueryAnalysis, RagQueryResult

MF = {"enrollment_year": {"from_year": 2022, "to_year": 2022}}


class FakePipeline:
    def __init__(self, result):
        self.result = result
        self.requests = []

    async def answer_email(self, request):
        self.requests.append(request)
        return self.result


def _analysis(question="Chuẩn ngoại ngữ K22?", inquiry_types=None, metadata_filter=None):
    return RagQueryAnalysis(
        original_question="Tiêu đề\nNội dung",
        effective_question=question,
        needs_rag=True,
        metadata_filter=metadata_filter or MF,
        inquiry_types=inquiry_types or ["training"],
    )


def _svc(result):
    svc = InquiryService.__new__(InquiryService)  # bypass __init__
    svc._rag_query = FakePipeline(result)
    return svc


async def test_process_maps_llm_pipeline_result():
    """Có file + FAQ → pipeline trả source=llm; inquiry giữ email-specific request options."""
    svc = _svc(RagQueryResult(
        answer_markdown="Câu trả lời tài liệu",
        source="llm",
        sources=[{"citationId": 1}],
        steps=[],
        token_usage=None,
        candidate_files=[{"file_id": "f1", "file_name": "Quy chế", "doc_description": "Mô tả"}],
        faq_docs=[object()],
        analysis=_analysis(inquiry_types=["graduation"]),
    ))
    faq_svc = MagicMock(log_interaction=AsyncMock())

    def close_background_coro(coro):
        coro.close()

    with patch("app.modules.email.workflows.inquiry_service.get_faq_service", AsyncMock(return_value=faq_svc)), \
        patch("app.modules.email.workflows.inquiry_service.asyncio.create_task", side_effect=close_background_coro):
        out = await svc.process("Tiêu đề", "Nội dung", message_id=123, to_rich_text=False, enrollment_year=2022)

    assert out["source"] == "llm"
    assert out["answer"] == "Câu trả lời tài liệu"
    assert out["question"] == "Chuẩn ngoại ngữ K22?"
    assert out["types"] == ["graduation"]
    assert out["filters"] == MF

    request = svc._rag_query.requests[0]
    assert request.mode == "email"
    assert request.question == "Tiêu đề\nNội dung"
    assert request.user_role == "student"
    assert request.email_subject == "Tiêu đề"
    assert request.email_content == "Nội dung"
    assert request.enrollment_year == 2022
    assert not hasattr(request, "resolve_citations")
    assert not hasattr(request, "citation_link_type")
    faq_svc.log_interaction.assert_called_once()


async def test_process_maps_faq_pipeline_result_without_sources():
    svc = _svc(RagQueryResult(
        answer_markdown="Câu trả lời FAQ",
        source="faq",
        sources=[{"should": "not be exposed"}],
        steps=[],
        token_usage=None,
        candidate_files=[],
        faq_docs=[object()],
        analysis=_analysis(),
    ))
    faq_svc = MagicMock(log_interaction=AsyncMock())

    def close_background_coro(coro):
        coro.close()

    with patch("app.modules.email.workflows.inquiry_service.get_faq_service", AsyncMock(return_value=faq_svc)), \
        patch("app.modules.email.workflows.inquiry_service.asyncio.create_task", side_effect=close_background_coro):
        out = await svc.process("Tiêu đề", "Nội dung", to_rich_text=False)

    assert out["source"] == "faq"
    assert out["sources"] == []
    assert out["answer"] == "Câu trả lời FAQ"
    faq_svc.log_interaction.assert_called_once()


async def test_process_maps_bypass_without_logging():
    """Retrieval context rỗng → bypass."""
    svc = _svc(RagQueryResult(
        answer_markdown="Không tìm thấy tài liệu phù hợp để trả lời email này.",
        source="bypass",
        sources=[],
        steps=[],
        token_usage=None,
        candidate_files=[],
        faq_docs=[],
        analysis=_analysis(question="Câu hỏi không có tài liệu?"),
    ))
    get_faq_service_mock = AsyncMock()

    with patch("app.modules.email.workflows.inquiry_service.get_faq_service", get_faq_service_mock), \
        patch("app.modules.email.workflows.inquiry_service.asyncio.create_task") as create_task:
        out = await svc.process("Tiêu đề", "Nội dung", message_id=123, to_rich_text=False)

    assert out["source"] == "bypass"
    get_faq_service_mock.assert_not_awaited()
    create_task.assert_not_called()


async def test_process_can_return_rich_text():
    svc = _svc(
        RagQueryResult(
            answer_markdown="**Câu trả lời**",
            source="llm",
            sources=[],
            steps=[],
            token_usage=None,
            candidate_files=[{"file_id": "f1", "file_name": "Quy chế", "doc_description": "Mô tả"}],
            faq_docs=[],
            analysis=_analysis(),
        ),
    )
    faq_svc = MagicMock(log_interaction=AsyncMock())

    def close_background_coro(coro):
        coro.close()

    with patch("app.modules.email.workflows.inquiry_service.get_faq_service", AsyncMock(return_value=faq_svc)), \
        patch("app.modules.email.workflows.inquiry_service.asyncio.create_task", side_effect=close_background_coro):
        out = await svc.process(
            "Tiêu đề",
            "Nội dung",
            message_id=123,
            to_rich_text=True,
            enrollment_year=2022,
        )

    assert "<strong>Câu trả lời</strong>" in out["answer"]
    request = svc._rag_query.requests[0]
    assert request.question == "Tiêu đề\nNội dung"
    faq_svc.log_interaction.assert_called_once()
