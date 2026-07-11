import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from app.modules.corpus.services.corpus_service import CorpusService, diff_links
from app.modules.corpus.models.corpus_node import CorpusNodeDocument
from app.modules.corpus.dtos.traversal import TraversalResult


def _node(node_key, files=None, faqs=None, children=None, parent=None):
    return SimpleNamespace(
        node_key=node_key,
        direct_file_ids=files or [],
        direct_faq_ids=faqs or [],
        child_keys=children or [],
        parent_key=parent,
    )


def test_diff_links():
    add, remove = diff_links(["a", "b"], ["b", "c"])
    assert add == ["c"]
    assert remove == ["a"]


@pytest.mark.asyncio
async def test_resolve_candidates_dedupes_and_intersects():
    svc = CorpusService()
    
    # Mock repo
    node1 = _node("topic1", files=["file1", "file2"], faqs=["faq1"])
    node2 = _node("topic2", files=["file2", "file3"], faqs=["faq2"])

    mock_repo = MagicMock()
    mock_repo.get_all = AsyncMock(return_value=[node1, node2])
    svc._repo = mock_repo

    # Case 1: no restrictions
    res = await svc.resolve_candidates(["topic1", "topic2"])
    assert len(res.file_candidates) == 3
    assert {c.leaf_id for c in res.file_candidates} == {"file1", "file2", "file3"}
    assert len(res.supporting_faqs) == 2
    assert {c.leaf_id for c in res.supporting_faqs} == {"faq1", "faq2"}

    # Case 2: allowed lists
    res = await svc.resolve_candidates(["topic1", "topic2"], allowed_files={"file2"}, allowed_faqs={"faq1"})
    assert len(res.file_candidates) == 1
    assert res.file_candidates[0].leaf_id == "file2"
    assert len(res.supporting_faqs) == 1
    assert res.supporting_faqs[0].leaf_id == "faq1"


@pytest.mark.asyncio
async def test_resolve_candidates_child_before_parent():
    svc = CorpusService()

    parent = _node("parent", files=["parent-file"], children=["child"])
    child = _node("child", files=["child-file"], parent="parent")

    mock_repo = MagicMock()
    mock_repo.get_all = AsyncMock(return_value=[parent, child])
    svc._repo = mock_repo

    res = await svc.resolve_candidates(["parent"], traversal_order=["parent", "child"])

    assert [c.leaf_id for c in res.file_candidates] == ["child-file", "parent-file"]


@pytest.mark.asyncio
async def test_resolve_candidates_prioritizes_selected_branch_before_depth():
    svc = CorpusService()

    a_parent = _node("a-parent", files=["a-parent-file"])
    b_parent = _node("b-parent", files=["b-parent-file"], children=["b-child"])
    b_child = _node("b-child", files=["b-child-file"], parent="b-parent")

    mock_repo = MagicMock()
    mock_repo.get_all = AsyncMock(return_value=[a_parent, b_parent, b_child])
    svc._repo = mock_repo

    res = await svc.resolve_candidates(["a-parent", "b-parent"])

    assert [c.leaf_id for c in res.file_candidates] == [
        "a-parent-file",
        "b-child-file",
        "b-parent-file",
    ]


@pytest.mark.asyncio
async def test_fetch_allowed_ids_uses_domain_services():
    svc = CorpusService()
    file_svc = MagicMock()
    file_svc.find_ids_for_corpus = AsyncMock(return_value={"file-1"})
    faq_svc = MagicMock()
    faq_svc.find_ids_for_corpus = AsyncMock(return_value={"faq-1"})

    with patch("app.modules.files.services.file_service.get_file_service", return_value=file_svc), \
        patch("app.modules.faq.services.faq_service.get_faq_service", AsyncMock(return_value=faq_svc)):
        file_ids, faq_ids = await svc.fetch_allowed_ids({"enrollment_year": {}}, "student")

    assert file_ids == {"file-1"}
    assert faq_ids == {"faq-1"}
    file_svc.find_ids_for_corpus.assert_awaited_once_with({"enrollment_year": {}}, "student")
    faq_svc.find_ids_for_corpus.assert_awaited_once_with({"enrollment_year": {}}, "student")


@pytest.mark.asyncio
async def test_reindex_leaf():
    svc = CorpusService()
    
    mock_repo = MagicMock()
    # current topics containing leaf
    current_node = MagicMock(spec=CorpusNodeDocument)
    current_node.node_key = "topic-old"
    mock_repo.get_topics_containing_leaf = AsyncMock(return_value=[current_node])
    mock_repo.add_leaf_link = AsyncMock()
    mock_repo.remove_leaf_link = AsyncMock()
    svc._repo = mock_repo

    new_topics = ["topic-new", "topic-same"]
    # We expect "topic-old" to be removed, and "topic-new", "topic-same" added
    # Since current was ["topic-old"], diff is: add=["topic-new", "topic-same"], remove=["topic-old"]
    await svc.reindex_leaf("file", "file123", new_topics)

    mock_repo.add_leaf_link.assert_any_call("topic-new", "file", "file123")
    mock_repo.add_leaf_link.assert_any_call("topic-same", "file", "file123")
    mock_repo.remove_leaf_link.assert_called_once_with("topic-old", "file", "file123")


@pytest.mark.asyncio
async def test_unindex_file_and_faq():
    svc = CorpusService()
    
    mock_repo = MagicMock()
    node = MagicMock(spec=CorpusNodeDocument)
    node.node_key = "topic1"
    mock_repo.get_topics_containing_leaf = AsyncMock(return_value=[node])
    mock_repo.remove_leaf_link = AsyncMock()
    svc._repo = mock_repo

    await svc.unindex_file("file123")
    mock_repo.remove_leaf_link.assert_called_once_with("topic1", "file", "file123")

    mock_repo.remove_leaf_link.reset_mock()
    await svc.unindex_faq("faq123")
    mock_repo.remove_leaf_link.assert_called_once_with("topic1", "faq", "faq123")
