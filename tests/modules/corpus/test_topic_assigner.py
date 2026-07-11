import json
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from app.modules.rag.ingestion.corpus_linker import CorpusLinker, assign_topics

ACTIVE = [
    ("chuan-dau-ra-ngoai-ngu", "Chuẩn đầu ra ngoại ngữ", "Quy định ngoại ngữ tốt nghiệp"),
    ("hoc-phi-mien-giam",      "Học phí & miễn giảm",    "Mức học phí và chính sách miễn giảm"),
    ("dieu-kien-tot-nghiep",   "Điều kiện tốt nghiệp",   "Các điều kiện để xét tốt nghiệp"),
]


@pytest.mark.asyncio
@patch("app.modules.rag.ingestion.corpus_linker.call_corpus_llm")
async def test_assign_topics_selects_valid(mock_call):
    mock_call.return_value = json.dumps({"selected": ["chuan-dau-ra-ngoai-ngu"], "new_topics": []})
    selected, new = await assign_topics("QĐ ngoại ngữ", "Tiếng Anh B1", ACTIVE)
    assert selected == ["chuan-dau-ra-ngoai-ngu"]
    assert new == []


@pytest.mark.asyncio
@patch("app.modules.rag.ingestion.corpus_linker.call_corpus_llm")
async def test_assign_topics_new_topic(mock_call):
    mock_call.return_value = json.dumps({
        "selected": [],
        "new_topics": [{"slug": "xet-chinh-sach", "title": "Xét chính sách", "summary": "Mô tả"}],
    })
    selected, new = await assign_topics("Chính sách học phí", "Nội dung", ACTIVE)
    assert selected == []
    assert len(new) == 1
    assert new[0].slug == "xet-chinh-sach"
    assert new[0].title == "Xét chính sách"


@pytest.mark.asyncio
@patch("app.modules.rag.ingestion.corpus_linker.call_corpus_llm")
async def test_assign_topics_bad_json_returns_empty(mock_call):
    mock_call.return_value = "not json at all"
    selected, new = await assign_topics("Tài liệu", "Nội dung", ACTIVE)
    assert selected == []
    assert new == []


@pytest.mark.asyncio
@patch("app.modules.rag.ingestion.corpus_linker.call_corpus_llm")
async def test_assign_topics_non_object_json_returns_empty(mock_call):
    mock_call.return_value = json.dumps(["not", "an", "object"])
    selected, new = await assign_topics("Tài liệu", "Nội dung", ACTIVE)
    assert selected == []
    assert new == []


@pytest.mark.asyncio
@patch("app.modules.rag.ingestion.corpus_linker.call_corpus_llm")
async def test_assign_topics_filters_unknown_keys(mock_call):
    mock_call.return_value = json.dumps({"selected": ["does-not-exist"], "new_topics": []})
    selected, new = await assign_topics("Tài liệu", "Nội dung", ACTIVE)
    assert selected == []


@pytest.mark.asyncio
@patch("app.modules.rag.ingestion.corpus_linker.call_corpus_llm")
async def test_assign_topics_empty_catalog_bootstraps_root_topics(mock_call):
    mock_call.return_value = json.dumps({
        "selected": ["khong-ton-tai"],
        "new_topics": [
            {"slug": "hoc-phi", "title": "Học phí", "summary": "Mô tả", "parent": "khong-ton-tai"},
        ],
    })

    selected, new = await assign_topics("Tài liệu", "Nội dung", [])

    assert selected == []
    assert len(new) == 1
    assert new[0].slug == "hoc-phi"
    assert new[0].parent is None
    mock_call.assert_called_once()


@pytest.mark.asyncio
@patch("app.modules.rag.ingestion.corpus_linker.call_corpus_llm")
async def test_assign_topics_empty_content_uses_name_only(mock_call):
    mock_call.return_value = json.dumps({"selected": ["chuan-dau-ra-ngoai-ngu"], "new_topics": []})
    selected, new = await assign_topics("QĐ ngoại ngữ", "", ACTIVE)
    assert selected == ["chuan-dau-ra-ngoai-ngu"]


@pytest.mark.asyncio
@patch("app.modules.rag.ingestion.corpus_linker.call_corpus_llm")
async def test_assign_topics_new_topic_with_valid_parent(mock_call):
    mock_call.return_value = json.dumps({
        "selected": [],
        "new_topics": [{
            "slug": "hoc-bong-doanh-nghiep", "title": "Học bổng doanh nghiệp",
            "summary": "Mô tả", "parent": "hoc-phi-mien-giam",
        }],
    })
    _, new = await assign_topics("QĐ học bổng", "Nội dung", ACTIVE)
    assert new[0].parent == "hoc-phi-mien-giam"


@pytest.mark.asyncio
@patch("app.modules.rag.ingestion.corpus_linker.call_corpus_llm")
async def test_assign_topics_new_topic_invalid_parent_becomes_none(mock_call):
    mock_call.return_value = json.dumps({
        "selected": [],
        "new_topics": [{
            "slug": "chu-de-moi", "title": "Chủ đề mới",
            "summary": "Mô tả", "parent": "khong-ton-tai",
        }],
    })
    _, new = await assign_topics("Tài liệu", "Nội dung", ACTIVE)
    assert new[0].parent is None


@pytest.mark.asyncio
@patch("app.modules.rag.ingestion.corpus_linker.call_corpus_llm")
async def test_assign_topics_empty_catalog_caps_new_topics_at_eight(mock_call):
    mock_call.return_value = json.dumps({
        "selected": [],
        "new_topics": [
            {"slug": f"chu-de-{i}", "title": f"Chủ đề {i}", "summary": "Mô tả"}
            for i in range(10)
        ],
    })

    _, new = await assign_topics("Tài liệu", "Nội dung", [])

    assert len(new) == 8


@pytest.mark.asyncio
@patch("app.modules.rag.ingestion.corpus_linker.call_corpus_llm")
async def test_assign_topics_caps_after_validating_new_topics(mock_call):
    mock_call.return_value = json.dumps({
        "selected": [],
        "new_topics": [
            {"slug": "", "title": ""},
            "not-a-topic",
            *[
                {"slug": f"chu-de-hop-le-{i}", "title": f"Chủ đề hợp lệ {i}", "summary": "Mô tả"}
                for i in range(8)
            ],
        ],
    })

    _, new = await assign_topics("Tài liệu", "Nội dung", [])

    assert len(new) == 8
    assert new[0].slug == "chu-de-hop-le-0"
    assert new[-1].slug == "chu-de-hop-le-7"


@pytest.mark.asyncio
@patch("app.modules.rag.ingestion.corpus_linker.call_corpus_llm")
async def test_assign_topics_new_topic_slug_only_uses_slug_as_title(mock_call):
    mock_call.return_value = json.dumps({
        "selected": [],
        "new_topics": [{"slug": "hoc-phi-moi", "summary": "Mô tả"}],
    })

    _, new = await assign_topics("Tài liệu", "Nội dung", [])

    assert len(new) == 1
    assert new[0].slug == "hoc-phi-moi"
    assert new[0].title == "hoc-phi-moi"


@pytest.mark.asyncio
@patch("app.modules.rag.ingestion.corpus_linker.call_corpus_llm")
async def test_assign_topics_sends_full_content_to_llm(mock_call):
    tail = "NOI_DUNG_TOC_CUOI_CAN_GIU"
    long_content = "x" * 2000 + tail
    mock_call.return_value = json.dumps({"selected": [], "new_topics": []})

    await assign_topics("Tài liệu", long_content, ACTIVE)

    prompt = mock_call.call_args.args[0]
    assert tail in prompt


@pytest.mark.asyncio
async def test_index_file_uses_doc_description_before_full_toc():
    indexer = CorpusLinker.__new__(CorpusLinker)
    indexer._ensure_topic_nodes = AsyncMock(return_value=["hoc-phi"])
    indexer._corpus_service = MagicMock()
    indexer._corpus_service.reindex_leaf = AsyncMock(return_value=["hoc-phi"])

    await indexer.index_file(
        "file1",
        display_name="Quy định học phí",
        doc_description="Tài liệu mô tả học phí.",
        toc_headings=["I. Tổng quan", "II. Miễn giảm", "III. Hoàn phí"],
    )

    indexer._ensure_topic_nodes.assert_awaited_once_with(
        "Quy định học phí",
        "Tài liệu mô tả học phí.\nI. Tổng quan\nII. Miễn giảm\nIII. Hoàn phí",
    )
    indexer._corpus_service.reindex_leaf.assert_awaited_once_with(
        "file", "file1", ["hoc-phi"]
    )
