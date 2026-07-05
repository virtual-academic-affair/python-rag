import json
from unittest.mock import MagicMock
from app.modules.corpus.services.corpus_traversal_service import CorpusTraversalService
from app.modules.corpus.models.corpus_node import CorpusNodeDocument


def _make_node(node_key, file_ids=None, faq_ids=None, title="", summary="",
               child_keys=None, parent_keys=None):
    n = MagicMock(spec=CorpusNodeDocument)
    n.node_key = node_key
    n.file_ids = file_ids or []
    n.faq_ids = faq_ids or []
    n.title = title or node_key
    n.summary = summary or ""
    n.child_keys = child_keys or []
    n.parent_keys = parent_keys or []
    return n


def _wire(svc, nodes):
    """Gắn repo mock: get_all trả toàn bộ nodes, get_by_keys lọc theo key."""
    async def mock_get_all():
        return nodes

    async def mock_get_by_keys(keys):
        return [n for n in nodes if n.node_key in keys]

    svc._repo = MagicMock()
    svc._repo.get_all = mock_get_all
    svc._repo.get_by_keys = mock_get_by_keys


async def test_traverse_unions_files_and_faqs_from_selected_topics():
    """Candidates = gộp file_ids/faq_ids từ các topic được LLM chọn."""
    svc = CorpusTraversalService()

    topic = _make_node(
        "topic:dieu-kien-tot-nghiep",
        file_ids=["file1", "file2"],
        faq_ids=["faqA"],
    )
    _wire(svc, [topic])

    async def mock_call_llm(prompt):
        return json.dumps({"selected_topics": ["topic:dieu-kien-tot-nghiep"]})

    svc._call_llm = mock_call_llm

    result = await svc.traverse("Điều kiện tốt nghiệp")

    assert [c.leaf_id for c in result.file_candidates] == ["file1", "file2"]
    assert [c.leaf_id for c in result.supporting_faqs] == ["faqA"]


async def test_traverse_dedupes_across_topics():
    """File nằm trong nhiều topic chỉ xuất hiện 1 lần."""
    svc = CorpusTraversalService()

    t1 = _make_node("topic:a", file_ids=["file1", "file2"])
    t2 = _make_node("topic:b", file_ids=["file2", "file3"])
    _wire(svc, [t1, t2])

    async def mock_call_llm(prompt):
        return json.dumps({"selected_topics": ["topic:a", "topic:b"]})

    svc._call_llm = mock_call_llm

    result = await svc.traverse("Câu hỏi")
    assert [c.leaf_id for c in result.file_candidates] == ["file1", "file2", "file3"]


async def test_select_topics_filters_invalid_keys():
    """_select_topics drops keys not in topic node list."""
    svc = CorpusTraversalService()

    topic_nodes = [_make_node("topic:hoc-phi-mien-giam")]

    async def mock_llm(prompt):
        return json.dumps({"selected_topics": ["topic:hoc-phi-mien-giam", "topic:does-not-exist"]})

    svc._call_llm = mock_llm

    selected = await svc._select_topics("Học phí?", topic_nodes)
    assert selected == ["topic:hoc-phi-mien-giam"]


async def test_traverse_empty_result_when_no_topics():
    """traverse returns empty TraversalResult when tree is empty."""
    svc = CorpusTraversalService()
    _wire(svc, [])

    result = await svc.traverse("Câu hỏi")
    assert result.file_candidates == []
    assert result.supporting_faqs == []


async def test_traverse_topics_drills_down_into_nested_topics():
    """Topic cha được chọn và có con → mở rộng thêm 1 tầng."""
    svc = CorpusTraversalService()

    child_topic = _make_node(
        "topic:hoc-bong-khuyen-khich", file_ids=["file-child"],
        parent_keys=["topic:hoc-bong"],
    )
    parent_topic = _make_node(
        "topic:hoc-bong",
        file_ids=["file-parent"],
        child_keys=["topic:hoc-bong-khuyen-khich"],
    )
    _wire(svc, [parent_topic, child_topic])

    call_count = {"n": 0}

    async def mock_select_topics(question, nodes, descendant_titles=None):
        call_count["n"] += 1
        return [n.node_key for n in nodes]

    svc._select_topics = mock_select_topics

    collected = await svc._traverse_topics("Học bổng khuyến khích học tập?")

    assert collected == ["topic:hoc-bong", "topic:hoc-bong-khuyen-khich"]
    assert call_count["n"] == 2  # hai vòng chọn (đã drill-down)


async def test_traverse_topics_no_depth_cap_reaches_level_four():
    """Không còn trần độ sâu — cây 4 tầng được duyệt hết khi LLM chọn liên tục."""
    svc = CorpusTraversalService()

    l4 = _make_node("topic:l4", file_ids=["f4"], parent_keys=["topic:l3"])
    l3 = _make_node("topic:l3", child_keys=["topic:l4"], parent_keys=["topic:l2"])
    l2 = _make_node("topic:l2", child_keys=["topic:l3"], parent_keys=["topic:l1"])
    l1 = _make_node("topic:l1", child_keys=["topic:l2"])
    _wire(svc, [l1, l2, l3, l4])

    async def mock_select_topics(question, nodes, descendant_titles=None):
        return [n.node_key for n in nodes]

    svc._select_topics = mock_select_topics

    collected = await svc._traverse_topics("Câu hỏi")
    assert collected == ["topic:l1", "topic:l2", "topic:l3", "topic:l4"]


async def test_traverse_topics_terminates_on_cyclic_data():
    """Data lỗi có vòng cha-con (A→B→A) vẫn kết thúc, không lặp vô hạn."""
    svc = CorpusTraversalService()

    a = _make_node("topic:a", child_keys=["topic:b"])
    b = _make_node("topic:b", child_keys=["topic:a"], parent_keys=["topic:a"])
    _wire(svc, [a, b])

    async def mock_select_topics(question, nodes, descendant_titles=None):
        return [n.node_key for n in nodes]

    svc._select_topics = mock_select_topics

    collected = await svc._traverse_topics("Câu hỏi")
    assert collected == ["topic:a", "topic:b"]  # mỗi node đúng 1 lần


async def test_traverse_topics_stops_when_llm_selects_nothing():
    """Termination: LLM không chọn topic nào → dừng, không drill-down."""
    svc = CorpusTraversalService()

    topic_node = _make_node("topic:hoc-phi", child_keys=["topic:hoc-phi-tra-gop"])
    _wire(svc, [topic_node])

    async def mock_select_topics(question, nodes, descendant_titles=None):
        return []

    svc._select_topics = mock_select_topics

    collected = await svc._traverse_topics("Thời tiết hôm nay?")
    assert collected == []


async def test_traverse_llm_failure_returns_empty_best_effort():
    """LLM lỗi hoàn toàn → traverse trả rỗng thay vì raise (best-effort)."""
    svc = CorpusTraversalService()

    topic_node = _make_node("topic:hoc-phi")
    _wire(svc, [topic_node])

    async def mock_call_llm(prompt):
        raise RuntimeError("LLM down")

    svc._call_llm = mock_call_llm

    result = await svc.traverse("Câu hỏi")
    assert result.file_candidates == []
    assert result.supporting_faqs == []


async def test_catalog_advertises_deep_descendants():
    """Node gốc phải kèm tên toàn bộ con cháu (kể cả tầng 3) trong catalog LLM."""
    svc = CorpusTraversalService()

    grandchild = _make_node(
        "topic:co-hoi-nghe-nghiep", title="Cơ hội nghề nghiệp",
        parent_keys=["topic:muc-tieu"],
    )
    child = _make_node(
        "topic:muc-tieu", title="Mục tiêu đào tạo",
        child_keys=["topic:co-hoi-nghe-nghiep"], parent_keys=["topic:goc"],
    )
    root = _make_node(
        "topic:goc", title="Tổ chức đào tạo",
        child_keys=["topic:muc-tieu"],
    )
    _wire(svc, [root, child, grandchild])

    prompts: list[str] = []

    async def mock_call_llm(prompt):
        prompts.append(prompt)
        return json.dumps({"selected_topics": []})

    svc._call_llm = mock_call_llm

    await svc._traverse_topics("Ra trường làm nghề gì?")

    # Catalog tầng gốc phải "quảng bá" cả con (Mục tiêu đào tạo) lẫn cháu (Cơ hội nghề nghiệp)
    assert len(prompts) == 1
    assert "Mục tiêu đào tạo" in prompts[0]
    assert "Cơ hội nghề nghiệp" in prompts[0]
