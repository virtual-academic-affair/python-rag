import inspect

import pytest
from unittest.mock import AsyncMock, MagicMock

from app.modules.corpus.models.corpus_node import CorpusNodeDocument
from app.modules.rag.query.retrieval.traversal.contracts import TraversalSession
from app.modules.rag.query.retrieval.traversal.runtime.activity import build_traversal_activity_steps
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
    session = TraversalSession(snapshot=snapshot, revealed_node_keys={"root"})

    expand, _inspect, select, _no_match = build_traversal_tools(session)

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
    session = TraversalSession(snapshot=snapshot, revealed_node_keys={"root"})
    expand, _inspect, select, _no_match = build_traversal_tools(session)

    assert (await expand("child"))["status"] == "invalid"
    await expand("root")
    result = await select([
        {"node_key": "root", "scope": "subtree"},
        {"node_key": "child", "scope": "direct"},
    ])
    assert result["status"] == "invalid"


def test_filtered_snapshot_builds_sorted_node_only_tree():
    root = _make_node("root", file_ids=["f1"], title="Gốc", child_keys=["z-child", "a-child"])
    root.subtree_file_ids = ["f1", "f2"]
    hidden = _make_node("z-child", file_ids=["hidden"], parent_key="root")
    visible = _make_node("a-child", file_ids=["f2"], title="Con", parent_key="root")

    snapshot = build_filtered_snapshot_from_nodes([hidden, root, visible], {"f1", "f2"}, set())

    assert [node.node_key for node in snapshot.topic_tree] == ["root"]
    assert [node.node_key for node in snapshot.topic_tree[0].children] == ["a-child"]
    assert snapshot.topic_tree[0].children[0].title == "Con"
    assert not hasattr(snapshot.topic_tree[0], "file_ids")


@pytest.mark.parametrize("include_reasoning", [False, True])
def test_inspect_topic_does_not_expose_sample_limit_to_agent(include_reasoning):
    root = _make_node("root", file_ids=["f1"])
    snapshot = build_filtered_snapshot_from_nodes([root], {"f1"}, set())
    session = TraversalSession(snapshot=snapshot, revealed_node_keys={"root"})

    _expand, inspect_topic, _select, _no_match = build_traversal_tools(
        session,
        include_reasoning=include_reasoning,
    )

    assert "sample_limit" not in inspect.signature(inspect_topic).parameters


def test_select_activity_returns_one_step_with_all_node_keys():
    first = _make_node("first", file_ids=["f1"], title="Một")
    second = _make_node("second", file_ids=["f2"], title="Hai")
    snapshot = build_filtered_snapshot_from_nodes([first, second], {"f1", "f2"}, set())

    steps = build_traversal_activity_steps(snapshot, "select_topics", {
        "status": "selected",
        "selectedTopics": [
            {"nodeKey": "first", "nodeTitle": "Một", "scope": "direct"},
            {"nodeKey": "second", "nodeTitle": "Hai", "scope": "direct"},
        ],
    })

    assert steps == [{
        "type": "corpus_traversal",
        "action": "select",
        "node_keys": ["first", "second"],
        "content": 'Chọn các chủ đề: "Một", "Hai".',
    }]
