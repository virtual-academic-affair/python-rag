"""Inquiry email flow: mock the shared RAG pipeline and email analyzer."""
from unittest.mock import AsyncMock, MagicMock, patch

from app.modules.email.workflows.inquiry_service import InquiryService
from app.modules.rag.query import RagQueryResult
from app.modules.rag.query.analyzer import EmailQueryAnalysis

MF = {"enrollment_year": {"from_year": 2022, "to_year": 2022}}


class FakePipeline:
    def __init__(self, result):
        self.result = result
        self.requests = []

    async def answer_email(self, request):
        self.requests.append(request)
        return self.result


class FakeEmailAnalyzer:
    def __init__(self, result):
        self.result = result
        self.requests = []

    async def analyze_email(self, title, content, sender_enrollment_year=None):
        self.requests.append((title, content, sender_enrollment_year))
        return self.result


def _svc(result, analysis=None):
    svc = InquiryService.__new__(InquiryService)  # bypass __init__
    svc._rag_query = FakePipeline(result)
    if analysis is not None:
        svc._email_analyzer = FakeEmailAnalyzer(analysis)
    return svc


async def test_faq_used_as_context_not_direct_answer():
    """Có file + FAQ → pipeline trả source=llm; inquiry giữ email-specific request options."""
    svc = _svc(RagQueryResult(
        answer_markdown="Câu trả lời tài liệu",
        source="llm",
        sources=[{"citationId": 1}],
        steps=[],
        token_usage=None,
        candidate_files=[{"file_id": "f1", "file_name": "Quy chế", "doc_description": "Mô tả"}],
        faq_docs=[object()],
    ))

    out = await svc._run_rag_pipeline("Chuẩn ngoại ngữ K22?", "Tiêu đề", "Nội dung", MF)

    assert out["source"] == "llm"
    assert out["answer"] == "Câu trả lời tài liệu"

    request = svc._rag_query.requests[0]
    assert request.mode == "email"
    assert request.question == "Chuẩn ngoại ngữ K22?"
    assert request.user_role == "student"
    assert request.resolve_citations is True
    assert request.citation_link_type == "original"


async def test_no_files_returns_bypass_even_with_faqs():
    """Không có file (dù có FAQ) → bypass. FAQ không bao giờ trả lời thẳng."""
    svc = _svc(RagQueryResult(
        answer_markdown="Không tìm thấy tài liệu phù hợp để trả lời email này.",
        source="bypass",
        sources=[],
        steps=[],
        token_usage=None,
        candidate_files=[],
        faq_docs=[object()],
    ))

    out = await svc._run_rag_pipeline("Câu hỏi", "Tiêu đề", "Nội dung", MF)

    assert out["source"] == "bypass"
    assert out["sources"] == []


async def test_empty_retrieval_context_falls_back_to_bypass():
    """Retrieval context rỗng → bypass."""
    svc = _svc(RagQueryResult(
        answer_markdown="Không tìm thấy tài liệu phù hợp để trả lời email này.",
        source="bypass",
        sources=[],
        steps=[],
        token_usage=None,
        candidate_files=[],
        faq_docs=[],
    ))

    out = await svc._run_rag_pipeline("Câu hỏi", "Tiêu đề", "Nội dung", MF)

    assert out["source"] == "bypass"


async def test_process_delegates_email_analysis_and_rag_pipeline():
    svc = _svc(
        RagQueryResult(
            answer_markdown="**Câu trả lời**",
            source="llm",
            sources=[],
            steps=[],
            token_usage=None,
            candidate_files=[{"file_id": "f1", "file_name": "Quy chế", "doc_description": "Mô tả"}],
            faq_docs=[],
        ),
        EmailQueryAnalysis(
            question="Chuẩn ngoại ngữ K22?",
            inquiry_types=["graduation"],
            metadata_filter=MF,
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
            to_rich_text=False,
            enrollment_year=2022,
        )

    assert out["answer"] == "**Câu trả lời**"
    assert out["question"] == "Chuẩn ngoại ngữ K22?"
    assert out["types"] == ["graduation"]
    assert out["filters"] == MF
    assert svc._email_analyzer.requests == [("Tiêu đề", "Nội dung", 2022)]
    request = svc._rag_query.requests[0]
    assert request.question == "Chuẩn ngoại ngữ K22?"
    assert request.metadata_filter == MF
    faq_svc.log_interaction.assert_called_once()


async def test_process_does_not_log_bypass_answer():
    svc = _svc(
        RagQueryResult(
            answer_markdown="Không tìm thấy tài liệu phù hợp để trả lời email này.",
            source="bypass",
            sources=[],
            steps=[],
            token_usage=None,
            candidate_files=[],
            faq_docs=[],
        ),
        EmailQueryAnalysis(
            question="Câu hỏi không có tài liệu?",
            inquiry_types=["training"],
            metadata_filter=MF,
        ),
    )
    get_faq_service_mock = AsyncMock()

    with patch("app.modules.email.workflows.inquiry_service.get_faq_service", get_faq_service_mock), \
        patch("app.modules.email.workflows.inquiry_service.asyncio.create_task") as create_task:
        out = await svc.process(
            "Tiêu đề",
            "Nội dung",
            message_id=123,
            to_rich_text=False,
        )

    assert out["source"] == "bypass"
    get_faq_service_mock.assert_not_awaited()
    create_task.assert_not_called()
