import json
import pytest
from unittest.mock import AsyncMock, MagicMock
from app.modules.corpus.services.corpus_traversal_service import CorpusTraversalService
from app.modules.corpus.models.corpus_node import CorpusNodeDocument, NodeStatus, NodeType
from app.modules.corpus.dtos.traversal import TraversalResult


def _make_node(node_key, node_type, file_ids=None, faq_ids=None, metadata_filter=None,
               title="", summary="", child_keys=None, status=NodeStatus.ACTIVE):
    n = MagicMock(spec=CorpusNodeDocument)
    n.node_key = node_key
    n.node_type = node_type
    n.file_ids = file_ids or []
    n.faq_ids = faq_ids or []
    n.metadata_filter = metadata_filter or {}
    n.title = title or node_key
    n.summary = summary or ""
    n.child_keys = child_keys or []
    n.status = status
    return n


async def test_traverse_with_topics_boosts_score():
    """Files under a selected topic + metadata node score higher than metadata-only."""
    svc = CorpusTraversalService()

    meta_node = _make_node(
        "type:quyet_dinh", NodeType.METADATA,
        file_ids=["file1"], metadata_filter={"type": "quyet_dinh"}
    )
    topic_node = _make_node(
        "topic:dieu-kien-tot-nghiep", NodeType.TOPIC,
        file_ids=["file1", "file2"],
        child_keys=["file:file1", "file:file2"],
    )

    async def mock_get_by_type(node_type, **_):
        if node_type == NodeType.METADATA:
            return [meta_node]
        return []

    async def mock_get_children(parent_key):
        if parent_key == "axis:topics":
            return [topic_node]
        return []

    async def mock_get_by_keys(keys):
        return [n for n in [meta_node, topic_node] if n.node_key in keys]

    async def mock_call_llm(prompt):
        return json.dumps({"selected_topics": ["topic:dieu-kien-tot-nghiep"]})

    svc._repo = MagicMock()
    svc._repo.get_by_type = mock_get_by_type
    svc._repo.get_children = mock_get_children
    svc._repo.get_by_keys = mock_get_by_keys
    svc._call_llm = mock_call_llm

    result = await svc.traverse("Điều kiện tốt nghiệp", {"type": "quyet_dinh"})

    file1 = next(c for c in result.file_candidates if c.leaf_id == "file1")
    file2 = next(c for c in result.file_candidates if c.leaf_id == "file2")

    # file1: metadata "keep" (0.6) + topic_match (+0.3) = 0.9
    assert file1.score == 0.9, f"Expected 0.9 for file1, got {file1.score}"
    # file2: topic only → classify({}, {"type":...}) = "low" (0.3) + topic_match (+0.3) = 0.6
    assert file2.score == 0.6, f"Expected 0.6 for file2, got {file2.score}"


async def test_traverse_no_topics_falls_back_to_metadata_only():
    """When no topic nodes exist, traverse behaves like Phase A."""
    svc = CorpusTraversalService()

    meta_node = _make_node(
        "enrollment_year:2020-2024", NodeType.METADATA,
        file_ids=["fileA"],
        metadata_filter={"enrollment_year": {"from_year": 2020, "to_year": 2024}}
    )

    async def mock_get_by_type(node_type, **_):
        if node_type == NodeType.METADATA:
            return [meta_node]
        return []

    async def mock_get_children(parent_key):
        return []

    async def mock_get_by_keys(keys):
        return [meta_node] if meta_node.node_key in keys else []

    svc._repo = MagicMock()
    svc._repo.get_by_type = mock_get_by_type
    svc._repo.get_children = mock_get_children
    svc._repo.get_by_keys = mock_get_by_keys

    result = await svc.traverse("Câu hỏi", {"enrollment_year": {"from_year": 2022, "to_year": 2022}})

    assert len(result.file_candidates) == 1
    assert result.file_candidates[0].leaf_id == "fileA"
    assert result.file_candidates[0].score == 0.6  # "keep" with no topic


async def test_select_topics_filters_invalid_keys():
    """_select_topics drops keys not in topic node list."""
    svc = CorpusTraversalService()

    topic_nodes = [
        _make_node("topic:hoc-phi-mien-giam", NodeType.TOPIC),
    ]

    async def mock_llm(prompt):
        return json.dumps({"selected_topics": ["topic:hoc-phi-mien-giam", "topic:does-not-exist"]})

    svc._call_llm = mock_llm

    selected = await svc._select_topics("Học phí?", topic_nodes)
    assert selected == ["topic:hoc-phi-mien-giam"]


async def test_traverse_empty_result_when_no_nodes():
    """traverse returns empty TraversalResult when no metadata nodes match."""
    svc = CorpusTraversalService()

    async def mock_get_by_type(node_type, **_):
        return []

    async def mock_get_children(parent_key):
        return []

    svc._repo = MagicMock()
    svc._repo.get_by_type = mock_get_by_type
    svc._repo.get_children = mock_get_children

    result = await svc.traverse("Câu hỏi", {})
    assert result.file_candidates == []
    assert result.supporting_faqs == []


async def test_traverse_metadata_drop_excludes_file():
    """Files from metadata nodes with conflicting metadata are excluded (drop)."""
    svc = CorpusTraversalService()

    # Node says K20-22 but query is for K25 — should be dropped
    meta_node = _make_node(
        "enrollment_year:2020-2022", NodeType.METADATA,
        file_ids=["fileX"],
        metadata_filter={"enrollment_year": {"from_year": 2020, "to_year": 2022}}
    )

    async def mock_get_by_type(node_type, **_):
        if node_type == NodeType.METADATA:
            return [meta_node]
        return []

    async def mock_get_children(parent_key):
        return []

    async def mock_get_by_keys(keys):
        return [meta_node] if meta_node.node_key in keys else []

    svc._repo = MagicMock()
    svc._repo.get_by_type = mock_get_by_type
    svc._repo.get_children = mock_get_children
    svc._repo.get_by_keys = mock_get_by_keys

    result = await svc.traverse("Câu hỏi K25", {"enrollment_year": {"from_year": 2025, "to_year": 2025}})

    assert result.file_candidates == []


async def test_traverse_topics_drills_down_into_nested_topics():
    """Stage 2: selected topic with topic children is expanded one more level."""
    svc = CorpusTraversalService()

    child_topic = _make_node(
        "topic:hoc-bong-khuyen-khich", NodeType.TOPIC,
        file_ids=["file-child"],
        child_keys=["file:file-child"],
    )
    parent_topic = _make_node(
        "topic:hoc-bong", NodeType.TOPIC,
        file_ids=["file-parent"],
        child_keys=["topic:hoc-bong-khuyen-khich", "file:file-parent"],
    )

    async def mock_get_children(parent_key):
        if parent_key == "axis:topics":
            return [parent_topic]
        if parent_key == "topic:hoc-bong":
            return [child_topic]
        return []

    call_count = {"n": 0}

    async def mock_select_topics(question, nodes):
        call_count["n"] += 1
        # Round 1 sees parent, round 2 sees child — select whatever is offered
        return [n.node_key for n in nodes]

    svc._repo = MagicMock()
    svc._repo.get_children = mock_get_children
    svc._select_topics = mock_select_topics

    collected = await svc._traverse_topics("Học bổng khuyến khích học tập?")

    assert collected == ["topic:hoc-bong", "topic:hoc-bong-khuyen-khich"]
    assert call_count["n"] == 2  # two LLM selection rounds (drill-down happened)


async def test_traverse_topics_stops_when_llm_selects_nothing():
    """Stage 2 termination: no relevant topics → stop without drilling down."""
    svc = CorpusTraversalService()

    topic_node = _make_node(
        "topic:hoc-phi", NodeType.TOPIC,
        child_keys=["topic:hoc-phi-tra-gop"],
    )

    async def mock_get_children(parent_key):
        if parent_key == "axis:topics":
            return [topic_node]
        return []

    async def mock_select_topics(question, nodes):
        return []

    svc._repo = MagicMock()
    svc._repo.get_children = mock_get_children
    svc._select_topics = mock_select_topics

    collected = await svc._traverse_topics("Thời tiết hôm nay?")
    assert collected == []


async def test_traverse_topics_skips_archived_nodes():
    """Archived topic nodes are excluded from LLM selection."""
    svc = CorpusTraversalService()

    active_node = _make_node("topic:con-hoat-dong", NodeType.TOPIC)
    archived_node = _make_node("topic:da-luu-tru", NodeType.TOPIC, status=NodeStatus.ARCHIVED)

    async def mock_get_children(parent_key):
        if parent_key == "axis:topics":
            return [active_node, archived_node]
        return []

    offered = []

    async def mock_select_topics(question, nodes):
        offered.extend(n.node_key for n in nodes)
        return []

    svc._repo = MagicMock()
    svc._repo.get_children = mock_get_children
    svc._select_topics = mock_select_topics

    await svc._traverse_topics("Câu hỏi")
    assert offered == ["topic:con-hoat-dong"]
