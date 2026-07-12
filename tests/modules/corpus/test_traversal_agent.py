import pytest
from unittest.mock import AsyncMock, MagicMock

from app.modules.corpus.models.corpus_node import CorpusNodeDocument
from app.modules.rag.query.retrieval.traversal.runtime.snapshot import build_filtered_snapshot_from_nodes
from app.modules.rag.query.retrieval.traversal.tools import build_traversal_tools


def _make_node(node_key, file_ids=None, faq_ids=None, title="", summary="", child_keys=None, parent_key=None):
    node = MagicMock(spec=CorpusNodeDocument)
    node.node_key = node_key
    node.direct_file_ids = file_ids or []
    node.direct_faq_ids = faq_ids or []
    node.subtree_file_ids = file_ids or []
    node.subtree_faq_ids = faq_ids or []
    node.title = title or node_key
    node.summary = summary
    node.child_keys = child_keys or []
    node.parent_key = parent_key
    return node


@pytest.mark.asyncio
async def test_tools_build_filtered_snapshot_expand_one_level_and_select_scope():
    root = _make_node("root", title="Gốc", child_keys=["child1", "child2"])
    child1 = _make_node("child1", file_ids=["f1"], title="Con 1", parent_key="root")
    child2 = _make_node("child2", file_ids=["f2"], title="Con 2", parent_key="root")
    root.subtree_file_ids = ["f1", "f2"]
    snapshot = build_filtered_snapshot_from_nodes([root, child1, child2], {"f1"}, set())

    list_roots, expand, _inspect, select, _no_match = build_traversal_tools(snapshot)

    roots = await list_roots()
    assert roots["status"] == "ok"
    assert roots["topics"][0]["counts"] == {
        "directFiles": 0,
        "directFaqs": 0,
        "subtreeFiles": 1,
        "subtreeFaqs": 0,
    }

    children = await expand("root")
    assert [item["nodeKey"] for item in children["topics"]] == ["child1"]

    selected = await select([{"node_key": "child1", "scope": "direct"}])
    assert selected["status"] == "selected"
    assert selected["totalFileCandidates"] == 1


@pytest.mark.asyncio
async def test_tools_reject_unrevealed_or_overlapping_selection():
    root = _make_node("root", child_keys=["child"])
    child = _make_node("child", file_ids=["f1"], parent_key="root")
    root.subtree_file_ids = ["f1"]
    snapshot = build_filtered_snapshot_from_nodes([root, child], {"f1"}, set())
    list_roots, expand, _inspect, select, _no_match = build_traversal_tools(snapshot)

    assert (await expand("root"))["status"] == "invalid"
    await list_roots()
    await expand("root")
    result = await select([
        {"node_key": "root", "scope": "subtree"},
        {"node_key": "child", "scope": "direct"},
    ])
    assert result["status"] == "invalid"
