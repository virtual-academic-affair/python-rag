"""FAQ hoạt động như file: lecturer_only cấp document, default False."""
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from pydantic import ValidationError

from app.modules.faq.models.faq import FaqDocument
from app.modules.faq.services.faq_service import FaqService
from app.modules.faq.dtos.create_faq import FaqCreateRequest, FaqBulkCreateItem
from app.modules.faq.dtos.update_faq import FaqUpdateRequest
from app.modules.faq.dtos.import_faq import FaqImportExcelRequest
from app.modules.faq.dtos.faq_out import FaqResponse
from app.modules.metadata.models.value_objects import FaqMetadata


def _make_doc(**kw):
    """FaqDocument không cần DB — model_construct bỏ qua validation Beanie."""
    defaults = dict(
        question="Câu hỏi mẫu?",
        question_unaccented="cau hoi mau?",
        answer_unaccented="tra loi",
        answer_markdown="trả lời",
        answer_rich_text="<p>trả lời</p>",
        lecturer_only=False,
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

    saved = await svc.update_faq("someid", {})
    assert saved.lecturer_only is True  # không truyền → giữ nguyên


@patch("app.modules.corpus.services.corpus_service.get_corpus_service")
@patch("app.modules.faq.services.faq_service.get_corpus_linker")
@patch("app.modules.faq.services.faq_service.get_metadata_service")
@patch("app.modules.faq.services.faq_service.FaqDocument")
async def test_create_faq_indexes_without_catalog_guard(mock_faq_doc, mock_meta_svc, mock_get_indexer, mock_get_corpus):
    mock_get_corpus.side_effect = AssertionError("catalog guard should not be called")
    meta = MagicMock()
    meta.validate_and_parse_faq_metadata.return_value = (True, [], FaqMetadata())
    mock_meta_svc.return_value = meta

    indexer = MagicMock()
    indexer.index_faq = AsyncMock(return_value=["topic:hoc-phi"])
    indexer.unindex_faq = AsyncMock()
    mock_get_indexer.return_value = indexer

    created_doc = _make_doc(id="faq1", question="Học phí?", answer_markdown="Trả lời")
    mock_faq_doc.return_value = created_doc
    repo = MagicMock()
    repo.create = AsyncMock(return_value=created_doc)
    repo.delete = AsyncMock()

    svc = FaqService.__new__(FaqService)
    svc._faq_repo = repo

    saved = await svc.create_faq("Học phí?", "<p>Trả lời</p>", {})

    assert saved is created_doc
    indexer.index_faq.assert_awaited_once()
    mock_get_corpus.assert_not_called()


@patch("app.modules.faq.services.faq_service.get_corpus_linker")
async def test_update_faq_keeps_existing_corpus_topics(mock_get_indexer):
    svc = FaqService.__new__(FaqService)
    doc = _make_doc(id="faq1", question="Câu hỏi cũ?")
    repo = MagicMock()
    repo.find_by_id = AsyncMock(return_value=doc)
    repo.save = AsyncMock(side_effect=lambda d: d)
    svc._faq_repo = repo

    saved = await svc.update_faq("faq1", {"question": "Câu hỏi mới?"})

    assert saved.question == "Câu hỏi mới?"
    mock_get_indexer.assert_not_called()


async def test_find_faq_ids_for_corpus_builds_filter_in_faq_domain():
    svc = FaqService.__new__(FaqService)
    repo = MagicMock()
    repo.find_ids_by_query = AsyncMock(return_value={"faq1"})
    svc._faq_repo = repo

    result = await svc.find_ids_for_corpus(
        {"enrollment_year": {"from_year": 2022, "to_year": 2022}},
        "student",
    )

    assert result == {"faq1"}
    query = repo.find_ids_by_query.await_args.args[0]
    assert query["deleted_at"] is None
    assert query["lecturer_only"] == {"$ne": True}
    assert query["metadata_filter.enrollment_year.from_year"] == {"$lte": 2022}


def test_dtos_expose_lecturer_only_with_safe_defaults():
    create = FaqCreateRequest(question="Câu hỏi mẫu?", answer_rich_text="<p>Trả lời</p>")
    assert create.lecturer_only is False
    item = FaqBulkCreateItem(question="Câu hỏi mẫu?", answer_rich_text="<p>Trả lời</p>")
    assert item.lecturer_only is False
    upd = FaqUpdateRequest()
    assert upd.lecturer_only is None
    imp = FaqImportExcelRequest(question_col="A", answer_col="B", metadata_filter_json="")
    assert imp.lecturer_only is False


def test_faq_update_rejects_removed_is_active_field():
    with pytest.raises(ValidationError):
        FaqUpdateRequest.model_validate({"isActive": False})


def test_faq_response_exposes_lecturer_only():
    doc = _make_doc(lecturer_only=True)
    resp = FaqResponse.from_document(doc)
    assert resp.lecturer_only is True
    payload = resp.model_dump(by_alias=True)
    assert "isActive" not in payload
    assert payload["deletedAt"] is None


async def test_list_faqs_exclude_lecturer_only_adds_condition():
    svc = FaqService.__new__(FaqService)
    captured = {}

    async def mock_list(metadata_filter=None, search_text=None, skip=0, limit=20):
        captured["metadata_filter"] = metadata_filter
        return [], 0

    repo = MagicMock()
    repo.list_faqs = mock_list
    svc._faq_repo = repo

    await svc.list_faqs(exclude_lecturer_only=True)
    assert captured["metadata_filter"] == {"lecturer_only": {"$ne": True}}


async def test_answer_from_faq_catalog_always_filters_lecturer_only():
    """Đường FAQ answer debug dùng catalog sinh viên → luôn ẩn FAQ lecturer_only."""
    svc = FaqService.__new__(FaqService)
    captured = {}

    async def mock_list(metadata_filter=None, search_text=None, skip=0, limit=20):
        captured["metadata_filter"] = metadata_filter
        return [], 0

    repo = MagicMock()
    repo.list_faqs = mock_list
    svc._faq_repo = repo

    result = await svc.answer_from_faq_catalog("Học phí?", {})
    assert result is None
    assert captured["metadata_filter"]["lecturer_only"] == {"$ne": True}
