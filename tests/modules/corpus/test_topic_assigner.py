import json
import pytest
from app.modules.corpus.topic_assigner import assign_topics

ACTIVE = [
    ("topic:chuan-dau-ra-ngoai-ngu", "Chuẩn đầu ra ngoại ngữ", "Quy định ngoại ngữ tốt nghiệp"),
    ("topic:hoc-phi-mien-giam",       "Học phí & miễn giảm",    "Mức học phí và chính sách miễn giảm"),
    ("topic:dieu-kien-tot-nghiep",    "Điều kiện tốt nghiệp",   "Các điều kiện để xét tốt nghiệp"),
]


async def _llm_select_first(prompt: str) -> str:
    return json.dumps({"selected": ["topic:chuan-dau-ra-ngoai-ngu"], "new_topics": []})


async def _llm_new_topic(prompt: str) -> str:
    return json.dumps({
        "selected": [],
        "new_topics": [{"slug": "xet-chinh-sach", "title": "Xét chính sách", "summary": "Mô tả"}],
    })


async def _llm_bad_json(prompt: str) -> str:
    return "not json at all"


async def _llm_unknown_key(prompt: str) -> str:
    return json.dumps({"selected": ["topic:does-not-exist"], "new_topics": []})


async def test_assign_topics_selects_valid():
    selected, new = await assign_topics("QĐ ngoại ngữ", "Tiếng Anh B1", ACTIVE, _llm_select_first)
    assert selected == ["topic:chuan-dau-ra-ngoai-ngu"]
    assert new == []


async def test_assign_topics_new_topic():
    selected, new = await assign_topics("Chính sách học phí", "Nội dung", ACTIVE, _llm_new_topic)
    assert selected == []
    assert len(new) == 1
    assert new[0]["slug"] == "xet-chinh-sach"


async def test_assign_topics_bad_json_returns_empty():
    selected, new = await assign_topics("Tài liệu", "Nội dung", ACTIVE, _llm_bad_json)
    assert selected == []
    assert new == []


async def test_assign_topics_filters_unknown_keys():
    selected, new = await assign_topics("Tài liệu", "Nội dung", ACTIVE, _llm_unknown_key)
    assert selected == []  # "topic:does-not-exist" not in valid_keys


async def test_assign_topics_empty_catalog_skips_llm():
    called = []

    async def _llm(prompt: str) -> str:
        called.append(prompt)
        return "{}"

    selected, new = await assign_topics("Tài liệu", "Nội dung", [], _llm)
    assert selected == []
    assert new == []
    assert called == []  # LLM not called when catalog is empty


async def test_assign_topics_empty_content_uses_name_only():
    selected, new = await assign_topics("QĐ ngoại ngữ", "", ACTIVE, _llm_select_first)
    assert selected == ["topic:chuan-dau-ra-ngoai-ngu"]
