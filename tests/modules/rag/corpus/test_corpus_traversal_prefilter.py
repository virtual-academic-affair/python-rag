"""Pre-filter 3 key trước traversal: lọc lá → ẩn folder rỗng → nới năm khi 0 lá."""
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


def _wire(svc, nodes, allowed_files=None, allowed_faqs=None):
    """Repo mock + allowed sets. allowed=None → cho phép mọi lá trong nodes."""
    if allowed_files is None:
        allowed_files = {fid for n in nodes for fid in n.file_ids}
    if allowed_faqs is None:
        allowed_faqs = {qid for n in nodes for qid in n.faq_ids}

    async def mock_get_all():
        return nodes

    async def mock_get_by_keys(keys):
        return [n for n in nodes if n.node_key in keys]

    svc._repo = MagicMock()
    svc._repo.get_all = mock_get_all
    svc._repo.get_by_keys = mock_get_by_keys

    fetch_calls = []

    async def mock_fetch_allowed(metadata_filter, user_role, relax_years=False):
        fetch_calls.append({"metadata_filter": metadata_filter,
                            "user_role": user_role, "relax_years": relax_years})
        return set(allowed_files), set(allowed_faqs)

    svc._fetch_allowed_ids = mock_fetch_allowed
    return fetch_calls


async def test_filtered_leaves_excluded_from_candidates():
    """Lá ngoài allowed set không xuất hiện trong kết quả dù topic được take."""
    svc = CorpusTraversalService()
    topic = _make_node("tot-nghiep", file_ids=["f-ok", "f-blocked"], faq_ids=["q-ok", "q-blocked"])
    _wire(svc, [topic], allowed_files={"f-ok"}, allowed_faqs={"q-ok"})

    async def mock_call_llm(prompt):
        return json.dumps({"decisions": [{"node": "tot-nghiep", "action": "take"}]})
    svc._call_llm = mock_call_llm

    result = await svc.traverse("Điều kiện tốt nghiệp K22?", metadata_filter={
        "enrollment_year": {"from_year": 2022, "to_year": 2022}}, user_role="student")

    assert [c.leaf_id for c in result.file_candidates] == ["f-ok"]
    assert [c.leaf_id for c in result.supporting_faqs] == ["q-ok"]


async def test_folder_empty_after_filter_hidden_from_llm():
    """Topic mà mọi lá bị lọc → không xuất hiện trong catalog LLM."""
    svc = CorpusTraversalService()
    visible = _make_node("hoc-phi", file_ids=["f-ok"])
    hidden = _make_node("giang-vien", file_ids=["f-blocked"])
    _wire(svc, [visible, hidden], allowed_files={"f-ok"}, allowed_faqs=set())

    offered = []

    async def mock_decide(question, nodes, descendant_titles=None):
        offered.extend(n.node_key for n in nodes)
        return []
    svc._decide_topics = mock_decide

    await svc.traverse("Học phí?", user_role="student")
    assert offered == ["hoc-phi"]


async def test_zero_leaves_relaxes_years_but_not_role():
    """0 lá sau lọc năm → gọi lại _fetch_allowed_ids với relax_years=True, cùng role."""
    svc = CorpusTraversalService()
    topic = _make_node("hoc-phi", file_ids=["f1"])
    # Lần đầu allowed rỗng → phải nới. Mock trả cùng set cả 2 lần nên
    # dùng fetch_calls để kiểm tra tham số từng lần gọi.
    fetch_calls = _wire(svc, [topic], allowed_files=set(), allowed_faqs=set())

    async def mock_decide(question, nodes, descendant_titles=None):
        return []
    svc._decide_topics = mock_decide

    mf = {"enrollment_year": {"from_year": 1990, "to_year": 1990}}
    result = await svc.traverse("Học phí?", metadata_filter=mf, user_role="student")

    assert len(fetch_calls) == 2
    assert fetch_calls[0]["relax_years"] is False
    assert fetch_calls[1]["relax_years"] is True
    assert fetch_calls[1]["user_role"] == "student"   # quyền không được nới
    assert result.prefilter["relaxed_years"] is True


async def test_zero_leaves_without_year_filter_does_not_relax():
    """Không có filter năm → 0 lá thì thôi, không re-query vô nghĩa."""
    svc = CorpusTraversalService()
    topic = _make_node("hoc-phi", file_ids=["f1"])
    fetch_calls = _wire(svc, [topic], allowed_files=set(), allowed_faqs=set())

    async def mock_decide(question, nodes, descendant_titles=None):
        return []
    svc._decide_topics = mock_decide

    result = await svc.traverse("Học phí?", user_role="student")
    assert len(fetch_calls) == 1
    assert result.file_candidates == []


async def test_prefilter_trace_reports_graph_leaf_counts():
    """prefilter trace đếm lá allowed TRONG graph (giao payload), không phải toàn DB."""
    svc = CorpusTraversalService()
    topic = _make_node("hoc-phi", file_ids=["f1", "f2"], faq_ids=["q1"])
    # f-db-only nằm trong allowed nhưng không gắn vào topic nào → không đếm
    _wire(svc, [topic], allowed_files={"f1", "f-db-only"}, allowed_faqs={"q1"})

    async def mock_decide(question, nodes, descendant_titles=None):
        return []
    svc._decide_topics = mock_decide

    result = await svc.traverse("Học phí?", user_role="student")
    assert result.prefilter == {"allowed_files": 1, "allowed_faqs": 1, "relaxed_years": False}


async def test_resolve_candidates_none_allowed_means_unrestricted():
    """resolve_candidates giữ tương thích: không truyền allowed → trả hết."""
    svc = CorpusTraversalService()
    topic = _make_node("hoc-phi", file_ids=["f1"], faq_ids=["q1"])

    async def mock_get_by_keys(keys):
        return [topic]
    svc._repo = MagicMock()
    svc._repo.get_by_keys = mock_get_by_keys

    result = await svc.resolve_candidates(["hoc-phi"])
    assert [c.leaf_id for c in result.file_candidates] == ["f1"]
    assert [c.leaf_id for c in result.supporting_faqs] == ["q1"]
