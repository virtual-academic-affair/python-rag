import pytest
from unittest.mock import AsyncMock, MagicMock
from app.modules.rag.query.retrieval.traversal.tools import build_traversal_tools
from app.modules.corpus.models.corpus_node import CorpusNodeDocument


def _make_node(node_key, file_ids=None, faq_ids=None, title="", summary="",
               child_keys=None, parent_key=None):
    n = MagicMock(spec=CorpusNodeDocument)
    n.node_key = node_key
    n.direct_file_ids = file_ids or []
    n.direct_faq_ids = faq_ids or []
    n.subtree_file_ids = file_ids or []
    n.subtree_faq_ids = faq_ids or []
    n.title = title or node_key
    n.summary = summary or ""
    n.child_keys = child_keys or []
    n.parent_key = parent_key
    return n


@pytest.mark.asyncio
async def test_traversal_tools_filtering_and_expansion():
    # Construct a small hierarchy:
    # root (parent_key=None) -> child1 (has allowed file)
    #                        -> child2 (has blocked file)
    root = _make_node("root", title="Gốc", child_keys=["child1", "child2"])
    child1 = _make_node("child1", title="Con 1", file_ids=["f1"], parent_key="root")
    child2 = _make_node("child2", title="Con 2", file_ids=["f2"], parent_key="root")
    root.subtree_file_ids = ["f1", "f2"]

    mock_repo = MagicMock()
    mock_repo.get_all = AsyncMock(return_value=[root, child1, child2])

    allowed_files = {"f1"}
    allowed_faqs = set()

    tools = build_traversal_tools(mock_repo, allowed_files, allowed_faqs)
    list_roots, expand, select = tools

    # 1. list_roots should only show root because it has child1 (which contains f1)
    roots_str = await list_roots()
    assert "root: Gốc" in roots_str
    assert "[1 tổng cả phân mục con]" in roots_str
    # child1 is visible because it has allowed content; child2 has f2 which is blocked
    assert "Con 1" in roots_str
    assert "Con 2" not in roots_str

    # 2. expand_topic("root") should return child1 but not child2
    expand_str = await expand("root")
    assert "child1" in expand_str
    assert "[1 mục trực tiếp]" in expand_str
    assert "child2" not in expand_str

    # 3. select_topics validates the final selection
    selection = await select(["child1", "child2", "missing"])
    assert selection["selected"] == ["child1"]
    assert selection["invalid"] == ["child2", "missing"]
    assert selection["expand_stack"] == ["root"]
    assert selection["total_files"] == 1
