import json
from unittest.mock import MagicMock
from app.modules.rag.corpus.services.corpus_traversal_service import CorpusTraversalService
from app.modules.rag.corpus.models.corpus_node import CorpusNodeDocument


def _make_node(node_key, file_ids=None, faq_ids=None, title="", summary="",
               child_keys=None, parent_key=None):
    n = MagicMock(spec=CorpusNodeDocument)
    n.node_key = node_key
    n.file_ids = file_ids or []
    n.faq_ids = faq_ids or []
    n.title = title or node_key
    n.summary = summary or ""
    n.child_keys = child_keys or []
    n.parent_key = parent_key
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


async def test_traverse_take_collects_files_and_faqs():
    """Quyết định 'take' → gộp file_ids/faq_ids của folder."""
    svc = CorpusTraversalService()

    topic = _make_node(
        "dieu-kien-tot-nghiep",
        file_ids=["file1", "file2"],
        faq_ids=["faqA"],
    )
    _wire(svc, [topic])

    async def mock_call_llm(prompt):
        return json.dumps({"decisions": [{"node": "dieu-kien-tot-nghiep", "action": "take"}]})

    svc._call_llm = mock_call_llm

    result = await svc.traverse("Điều kiện tốt nghiệp")

    assert [c.leaf_id for c in result.file_candidates] == ["file1", "file2"]
    assert [c.leaf_id for c in result.supporting_faqs] == ["faqA"]


async def test_traverse_take_includes_whole_subtree():
    """'take' folder cha → lấy luôn candidates của mọi folder con, không cần mở."""
    svc = CorpusTraversalService()

    child = _make_node("hoc-bong-khuyen-khich", file_ids=["file-child"], parent_key="hoc-bong")
    parent = _make_node("hoc-bong", file_ids=["file-parent"], child_keys=["hoc-bong-khuyen-khich"])
    _wire(svc, [parent, child])

    calls = {"n": 0}

    async def mock_call_llm(prompt):
        calls["n"] += 1
        return json.dumps({"decisions": [{"node": "hoc-bong", "action": "take"}]})

    svc._call_llm = mock_call_llm

    result = await svc.traverse("Học bổng?")

    assert [c.leaf_id for c in result.file_candidates] == ["file-parent", "file-child"]
    assert calls["n"] == 1  # take → dừng ngay, không mở tầng dưới


async def test_traverse_open_drills_down_without_taking_parent_files():
    """'open' folder cha → mở con xem tiếp, KHÔNG lấy file của cha."""
    svc = CorpusTraversalService()

    child = _make_node("hoc-bong-khuyen-khich", file_ids=["file-child"], parent_key="hoc-bong")
    parent = _make_node("hoc-bong", file_ids=["file-parent"], child_keys=["hoc-bong-khuyen-khich"])
    _wire(svc, [parent, child])

    call_order = []

    async def mock_decide(question, nodes, descendant_titles=None):
        keys = [n.node_key for n in nodes]
        call_order.append(keys)
        if "hoc-bong" in keys:
            return [("hoc-bong", "open")]
        return [("hoc-bong-khuyen-khich", "take")]

    svc._decide_topics = mock_decide

    result = await svc.traverse("Học bổng khuyến khích học tập?")

    assert call_order == [["hoc-bong"], ["hoc-bong-khuyen-khich"]]
    # Chỉ lấy file của con — file của cha bị bỏ vì cha chọn "open"
    assert [c.leaf_id for c in result.file_candidates] == ["file-child"]


async def test_traverse_open_on_leaf_folder_treated_as_take():
    """'open' folder không có con → coi như 'take' (không mất dữ liệu)."""
    svc = CorpusTraversalService()

    leaf = _make_node("hoc-phi", file_ids=["f1"])
    _wire(svc, [leaf])

    async def mock_decide(question, nodes, descendant_titles=None):
        return [("hoc-phi", "open")]

    svc._decide_topics = mock_decide

    collected = await svc._traverse_topics("Học phí?")
    assert collected == ["hoc-phi"]


async def test_traverse_dedupes_across_topics():
    """File nằm trong nhiều topic chỉ xuất hiện 1 lần."""
    svc = CorpusTraversalService()

    t1 = _make_node("a", file_ids=["file1", "file2"])
    t2 = _make_node("b", file_ids=["file2", "file3"])
    _wire(svc, [t1, t2])

    async def mock_call_llm(prompt):
        return json.dumps({"decisions": [
            {"node": "a", "action": "take"},
            {"node": "b", "action": "take"},
        ]})

    svc._call_llm = mock_call_llm

    result = await svc.traverse("Câu hỏi")
    assert [c.leaf_id for c in result.file_candidates] == ["file1", "file2", "file3"]


async def test_decide_topics_filters_invalid_keys_and_actions():
    """_decide_topics loại key không tồn tại và action lạ."""
    svc = CorpusTraversalService()

    topic_nodes = [_make_node("hoc-phi-mien-giam")]

    async def mock_llm(prompt):
        return json.dumps({"decisions": [
            {"node": "hoc-phi-mien-giam", "action": "take"},
            {"node": "does-not-exist", "action": "take"},
            {"node": "hoc-phi-mien-giam", "action": "delete"},
        ]})

    svc._call_llm = mock_llm

    decisions = await svc._decide_topics("Học phí?", topic_nodes)
    assert decisions == [("hoc-phi-mien-giam", "take")]


async def test_traverse_empty_result_when_no_topics():
    """traverse returns empty TraversalResult when tree is empty."""
    svc = CorpusTraversalService()
    _wire(svc, [])

    result = await svc.traverse("Câu hỏi")
    assert result.file_candidates == []
    assert result.supporting_faqs == []


async def test_traverse_skips_empty_subtrees():
    """Filter trước khi travel: node mà subtree không có file/FAQ nào thì không đưa cho LLM."""
    svc = CorpusTraversalService()

    full = _make_node("co-noi-dung", file_ids=["file1"])
    empty_child = _make_node("rong-con", parent_key="rong")
    empty = _make_node("rong", child_keys=["rong-con"])
    _wire(svc, [full, empty, empty_child])

    offered_keys: list[str] = []

    async def mock_decide(question, nodes, descendant_titles=None):
        offered_keys.extend(n.node_key for n in nodes)
        return []

    svc._decide_topics = mock_decide

    await svc._traverse_topics("Câu hỏi")
    assert offered_keys == ["co-noi-dung"]  # nhánh rỗng bị loại trước khi LLM nhìn thấy


async def test_traverse_topics_no_depth_cap_reaches_level_four():
    """Không còn trần độ sâu — chuỗi 'open' đi tới tầng 4 rồi 'take'."""
    svc = CorpusTraversalService()

    l4 = _make_node("l4", file_ids=["f4"], parent_key="l3")
    l3 = _make_node("l3", child_keys=["l4"], parent_key="l2")
    l2 = _make_node("l2", child_keys=["l3"], parent_key="l1")
    l1 = _make_node("l1", child_keys=["l2"])
    _wire(svc, [l1, l2, l3, l4])

    async def mock_decide(question, nodes, descendant_titles=None):
        # Mở mọi folder còn con; take folder lá
        out = []
        for n in nodes:
            out.append((n.node_key, "open" if n.child_keys else "take"))
        return out

    svc._decide_topics = mock_decide

    collected = await svc._traverse_topics("Câu hỏi")
    assert collected == ["l4"]  # chuỗi open l1→l2→l3, take l4


async def test_traverse_topics_terminates_on_cyclic_data():
    """Data lỗi có vòng cha-con (A→B→A) vẫn kết thúc, không lặp vô hạn."""
    svc = CorpusTraversalService()

    a = _make_node("a", file_ids=["f1"], child_keys=["b"])
    b = _make_node("b", file_ids=["f2"], child_keys=["a"], parent_key="a")
    _wire(svc, [a, b])

    async def mock_decide(question, nodes, descendant_titles=None):
        return [(n.node_key, "open") for n in nodes]

    svc._decide_topics = mock_decide

    collected = await svc._traverse_topics("Câu hỏi")
    # a mở → b; b mở → a đã offered → dừng. Không node nào được take → rỗng, nhưng kết thúc.
    assert collected == []


async def test_traverse_topics_stops_when_llm_skips_everything():
    """Termination: LLM bỏ qua tất cả folder → dừng, không drill-down."""
    svc = CorpusTraversalService()

    child = _make_node("hoc-phi-tra-gop", file_ids=["f1"], parent_key="hoc-phi")
    topic_node = _make_node("hoc-phi", file_ids=["f0"], child_keys=["hoc-phi-tra-gop"])
    _wire(svc, [topic_node, child])

    async def mock_decide(question, nodes, descendant_titles=None):
        return []

    svc._decide_topics = mock_decide

    collected = await svc._traverse_topics("Thời tiết hôm nay?")
    assert collected == []


async def test_traverse_llm_failure_returns_empty_best_effort():
    """LLM lỗi hoàn toàn → traverse trả rỗng thay vì raise (best-effort)."""
    svc = CorpusTraversalService()

    topic_node = _make_node("hoc-phi", file_ids=["f1"])
    _wire(svc, [topic_node])

    async def mock_call_llm(prompt):
        raise RuntimeError("LLM down")

    svc._call_llm = mock_call_llm

    result = await svc.traverse("Câu hỏi")
    assert result.file_candidates == []
    assert result.supporting_faqs == []


async def test_catalog_advertises_deep_descendants():
    """Folder gốc phải kèm tên các folder con cháu CÓ nội dung trong catalog LLM."""
    svc = CorpusTraversalService()

    grandchild = _make_node(
        "co-hoi-nghe-nghiep", title="Cơ hội nghề nghiệp",
        file_ids=["f1"], parent_key="muc-tieu",
    )
    child = _make_node(
        "muc-tieu", title="Mục tiêu đào tạo",
        child_keys=["co-hoi-nghe-nghiep"], parent_key="goc",
    )
    root = _make_node(
        "goc", title="Tổ chức đào tạo",
        child_keys=["muc-tieu"],
    )
    _wire(svc, [root, child, grandchild])

    prompts: list[str] = []

    async def mock_call_llm(prompt):
        prompts.append(prompt)
        return json.dumps({"decisions": []})

    svc._call_llm = mock_call_llm

    await svc._traverse_topics("Ra trường làm nghề gì?")

    # Catalog tầng gốc phải "quảng bá" cả con (Mục tiêu đào tạo) lẫn cháu (Cơ hội nghề nghiệp)
    assert len(prompts) == 1
    assert "Mục tiêu đào tạo" in prompts[0]
    assert "Cơ hội nghề nghiệp" in prompts[0]
