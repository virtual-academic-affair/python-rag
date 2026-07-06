"""FAQ hoạt động như file: lecturer_only cấp document, default False."""
from unittest.mock import AsyncMock, MagicMock

from app.modules.faq.models.faq import FaqDocument
from app.modules.faq.services.faq_service import FaqService
from app.modules.faq.dtos.create_faq import FaqCreateRequest, FaqBulkCreateItem
from app.modules.faq.dtos.update_faq import FaqUpdateRequest
from app.modules.faq.dtos.import_faq import FaqImportExcelRequest
from app.modules.faq.dtos.faq_out import FaqResponse


def _make_doc(**kw):
    """FaqDocument không cần DB — model_construct bỏ qua validation Beanie."""
    defaults = dict(
        question="Câu hỏi mẫu?",
        question_unaccented="cau hoi mau?",
        answer_unaccented="tra loi",
        answer_markdown="trả lời",
        answer_rich_text="<p>trả lời</p>",
        lecturer_only=False,
        is_active=True,
        view_count=0,
        source="manual",
        metadata_filter=None,
        created_at=None,
        updated_at=None,
    )
    defaults.update(kw)
    return FaqDocument.model_construct(**defaults)


def test_faq_document_lecturer_only_defaults_false():
    doc = FaqDocument.model_construct(
        question="Câu hỏi mẫu?",
        question_unaccented="cau hoi mau?",
        answer_unaccented="tra loi",
        answer_markdown="trả lời",
    )
    # model_construct không áp default → kiểm tra qua model field
    assert FaqDocument.model_fields["lecturer_only"].default is False
    doc2 = _make_doc()
    assert doc2.lecturer_only is False


async def test_update_faq_sets_lecturer_only():
    svc = FaqService.__new__(FaqService)  # bỏ qua __init__ (tạo repo thật)
    doc = _make_doc(lecturer_only=False)
    repo = MagicMock()
    repo.find_by_id = AsyncMock(return_value=doc)
    repo.save = AsyncMock(side_effect=lambda d: d)
    svc._faq_repo = repo

    saved = await svc.update_faq("someid", {"lecturer_only": True})
    assert saved.lecturer_only is True


async def test_update_faq_ignores_absent_lecturer_only():
    svc = FaqService.__new__(FaqService)
    doc = _make_doc(lecturer_only=True)
    repo = MagicMock()
    repo.find_by_id = AsyncMock(return_value=doc)
    repo.save = AsyncMock(side_effect=lambda d: d)
    svc._faq_repo = repo

    saved = await svc.update_faq("someid", {"is_active": False})
    assert saved.lecturer_only is True  # không truyền → giữ nguyên


def test_dtos_expose_lecturer_only_with_safe_defaults():
    create = FaqCreateRequest(question="Câu hỏi mẫu?", answer_rich_text="<p>Trả lời</p>")
    assert create.lecturer_only is False
    item = FaqBulkCreateItem(question="Câu hỏi mẫu?", answer_rich_text="<p>Trả lời</p>")
    assert item.lecturer_only is False
    upd = FaqUpdateRequest()
    assert upd.lecturer_only is None
    imp = FaqImportExcelRequest(question_col="A", answer_col="B", metadata_filter_json="")
    assert imp.lecturer_only is False


def test_faq_response_exposes_lecturer_only():
    doc = _make_doc(lecturer_only=True)
    resp = FaqResponse.from_document(doc)
    assert resp.lecturer_only is True


async def test_list_faqs_exclude_lecturer_only_adds_condition():
    svc = FaqService.__new__(FaqService)
    captured = {}

    async def mock_list(is_active=None, metadata_filter=None, search_text=None, skip=0, limit=20):
        captured["metadata_filter"] = metadata_filter
        return [], 0

    repo = MagicMock()
    repo.list_faqs = mock_list
    svc._faq_repo = repo

    await svc.list_faqs(exclude_lecturer_only=True)
    assert captured["metadata_filter"] == {"lecturer_only": {"$ne": True}}


async def test_find_best_match_always_filters_lecturer_only():
    """Đường find_best_match phục vụ email sinh viên → luôn ẩn FAQ lecturer_only."""
    svc = FaqService.__new__(FaqService)
    captured = {}

    async def mock_list(is_active=None, metadata_filter=None, search_text=None, skip=0, limit=20):
        captured["metadata_filter"] = metadata_filter
        return [], 0

    repo = MagicMock()
    repo.list_faqs = mock_list
    svc._faq_repo = repo

    result = await svc.find_best_match("Học phí?", {})
    assert result is None
    assert captured["metadata_filter"]["lecturer_only"] == {"$ne": True}
