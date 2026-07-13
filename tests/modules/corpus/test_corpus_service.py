import pytest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from app.modules.corpus.repositories.corpus_node_repository import CorpusNodeRepository
from app.modules.corpus.services.corpus_service import CorpusService, diff_links
from app.modules.corpus.models.corpus_node import CorpusNodeDocument
from app.modules.corpus.dtos.topic_out import CorpusFaqRefResponse, CorpusFileRefResponse
from app.modules.metadata.models.value_objects import FaqMetadata, FileMetadata


def _node(node_key, files=None, faqs=None, children=None, parent=None):
    files = files or []
    faqs = faqs or []
    return SimpleNamespace(
        node_key=node_key,
        title=node_key,
        summary="",
        direct_file_ids=files,
        direct_faq_ids=faqs,
        subtree_file_ids=list(files),
        subtree_faq_ids=list(faqs),
        child_keys=children or [],
        parent_key=parent,
        file_count=len(files),
        faq_count=len(faqs),
    )


def test_diff_links():
    add, remove = diff_links(["a", "b"], ["b", "c"])
    assert add == ["c"]
    assert remove == ["a"]


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
async def test_backfill_does_not_require_existing_topic_catalog():
    svc = CorpusService()
    repo = MagicMock()
    repo.reset_all_links = AsyncMock()
    repo.assert_integrity = AsyncMock()
    svc._repo = repo

    file_query = MagicMock()
    file_query.skip.return_value.limit.return_value.to_list = AsyncMock(return_value=[])
    faq_query = MagicMock()
    faq_query.skip.return_value.limit.return_value.to_list = AsyncMock(return_value=[])
    with patch("app.modules.files.models.file.FileDocument.find", return_value=file_query), patch(
        "app.modules.faq.models.faq.FaqDocument.find", return_value=faq_query
    ), patch("app.modules.rag.ingestion.corpus_linker.get_corpus_linker", return_value=MagicMock()):
        await svc.backfill_corpus()

    repo.reset_all_links.assert_awaited_once()
    repo.assert_integrity.assert_awaited_once()
    repo.get_all.assert_not_called()


@pytest.mark.asyncio
async def test_reindex_payload():
    svc = CorpusService()
    
    mock_repo = MagicMock()
    # current nodes containing payload
    current_node = MagicMock(spec=CorpusNodeDocument)
    current_node.node_key = "topic-old"
    mock_repo.get_nodes_containing_payload = AsyncMock(return_value=[current_node])
    mock_repo.get_by_keys = AsyncMock(return_value=[
        _node("topic-new"),
        _node("topic-same"),
    ])
    mock_repo.add_payload_link = AsyncMock()
    mock_repo.remove_payload_link = AsyncMock()
    svc._repo = mock_repo

    new_nodes = ["topic-new", "topic-same"]
    # We expect "topic-old" to be removed, and "topic-new", "topic-same" added
    # Since current was ["topic-old"], diff is: add=["topic-new", "topic-same"], remove=["topic-old"]
    await svc.reindex_payload("file", "file123", new_nodes)

    mock_repo.add_payload_link.assert_any_call("topic-new", "file", "file123")
    mock_repo.add_payload_link.assert_any_call("topic-same", "file", "file123")
    mock_repo.remove_payload_link.assert_called_once_with("topic-old", "file", "file123")


@pytest.mark.asyncio
async def test_reindex_payload_rejects_unknown_node_key():
    svc = CorpusService()

    mock_repo = MagicMock()
    mock_repo.get_by_keys = AsyncMock(return_value=[_node("topic-ok")])
    mock_repo.get_nodes_containing_payload = AsyncMock()
    mock_repo.add_payload_link = AsyncMock()
    mock_repo.remove_payload_link = AsyncMock()
    svc._repo = mock_repo

    with pytest.raises(ValueError, match="Unknown corpus node keys"):
        await svc.reindex_payload("file", "file123", ["topic-ok", "topic-missing"])

    mock_repo.get_nodes_containing_payload.assert_not_awaited()
    mock_repo.add_payload_link.assert_not_awaited()
    mock_repo.remove_payload_link.assert_not_awaited()


@pytest.mark.asyncio
async def test_build_tree_hydrates_direct_file_and_faq_names_in_batch():
    svc = CorpusService()
    root = _node("root", files=["file-1", "stale-file"], faqs=["faq-1"])
    repo = MagicMock()
    repo.get_all = AsyncMock(return_value=[root])
    svc._repo = repo
    svc._load_payload_name_maps = AsyncMock(return_value=(
        {"file-1": CorpusFileRefResponse(id="file-1", name="Quy chế đào tạo")},
        {"faq-1": CorpusFaqRefResponse(id="faq-1", name="Điều kiện tốt nghiệp?")},
    ))

    response = await svc.build_tree()

    tree_root = response.tree[0]
    assert [(item.id, item.name) for item in tree_root.direct_files] == [
        ("file-1", "Quy chế đào tạo"),
        ("stale-file", ""),
    ]
    assert [(item.id, item.name) for item in tree_root.direct_faqs] == [
        ("faq-1", "Điều kiện tốt nghiệp?"),
    ]


@pytest.mark.asyncio
async def test_build_tree_filters_payloads_counts_and_empty_branches_consistently():
    svc = CorpusService()
    root = _node("root", children=["matching", "hidden"])
    root.subtree_file_ids = ["file-match", "file-hidden"]
    root.subtree_faq_ids = ["faq-match"]
    root.file_count = 2
    root.faq_count = 1
    matching = _node("matching", files=["file-match"], faqs=["faq-match"], parent="root")
    hidden = _node("hidden", files=["file-hidden"], parent="root")
    repo = MagicMock()
    repo.get_all = AsyncMock(return_value=[root, matching, hidden])
    svc._repo = repo
    svc.fetch_allowed_ids = AsyncMock(return_value=({"file-match"}, {"faq-match"}))
    svc._load_payload_name_maps = AsyncMock(return_value=(
        {"file-match": CorpusFileRefResponse(id="file-match", name="File phù hợp")},
        {"faq-match": CorpusFaqRefResponse(id="faq-match", name="FAQ phù hợp")},
    ))
    metadata_filter = {
        "enrollment_year": {"from_year": 2022, "to_year": 2022},
        "academic_year": {"from_year": 2024, "to_year": 2024},
    }

    response = await svc.build_tree(metadata_filter=metadata_filter, lecturer_only=True)

    svc.fetch_allowed_ids.assert_awaited_once_with(metadata_filter, "admin", lecturer_only=True)
    assert response.total_nodes == 2
    assert response.total_root_nodes == 1
    tree_root = response.tree[0]
    assert tree_root.file_count == 1
    assert tree_root.faq_count == 1
    assert [child.node_key for child in tree_root.children] == ["matching"]
    assert tree_root.children[0].direct_files[0].name == "File phù hợp"


@pytest.mark.asyncio
async def test_payload_name_maps_use_one_deduplicated_batch_per_payload_type():
    svc = CorpusService()
    nodes = [
        _node("a", files=["file-1", "file-2"], faqs=["faq-1"]),
        _node("b", files=["file-1"], faqs=["faq-1", "faq-2"]),
    ]
    file_svc = MagicMock()
    file_svc.get_files_by_ids = AsyncMock(return_value=[
        SimpleNamespace(
            id="file-1",
            display_name="File 1",
            original_filename="file-1.pdf",
            custom_metadata=FileMetadata(),
            lecturer_only=True,
            updated_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        ),
        SimpleNamespace(
            id="file-2",
            display_name="",
            original_filename="file-2.pdf",
            custom_metadata=FileMetadata(),
            lecturer_only=False,
            updated_at=datetime(2026, 1, 3, tzinfo=timezone.utc),
        ),
    ])
    faq_svc = MagicMock()
    faq_svc.get_faqs_by_ids = AsyncMock(return_value=[
        SimpleNamespace(
            id="faq-1",
            question="FAQ 1",
            metadata_filter=FaqMetadata(),
            lecturer_only=True,
            updated_at=datetime(2026, 1, 4, tzinfo=timezone.utc),
        ),
        SimpleNamespace(
            id="faq-2",
            question="FAQ 2",
            metadata_filter=FaqMetadata(),
            lecturer_only=False,
            updated_at=datetime(2026, 1, 5, tzinfo=timezone.utc),
        ),
    ])

    with patch("app.modules.files.services.file_service.get_file_service", return_value=file_svc), \
        patch("app.modules.faq.services.faq_service.get_faq_service", AsyncMock(return_value=faq_svc)):
        file_payloads, faq_payloads = await svc._load_payload_name_maps(nodes)

    file_svc.get_files_by_ids.assert_awaited_once_with(["file-1", "file-2"])
    faq_svc.get_faqs_by_ids.assert_awaited_once_with(["faq-1", "faq-2"])
    assert file_payloads["file-1"].name == "File 1"
    assert file_payloads["file-1"].lecturer_only is True
    assert file_payloads["file-1"].metadata.enrollment_year.from_year == 0
    assert file_payloads["file-2"].updated_at == datetime(2026, 1, 3, tzinfo=timezone.utc)
    assert faq_payloads["faq-1"].name == "FAQ 1"
    assert faq_payloads["faq-1"].lecturer_only is True
    assert faq_payloads["faq-2"].metadata.academic_year.to_year == 9999


@pytest.mark.asyncio
async def test_update_payload_topics_validates_payload_and_replaces_deduplicated_membership():
    svc = CorpusService()
    svc._get_payload_name = AsyncMock(return_value="Quy chế đào tạo")
    svc.reindex_payload = AsyncMock(return_value=["topic-a", "topic-b"])

    response = await svc.update_payload_topics(
        "file",
        "file-1",
        ["topic-a", "topic-a", "topic-b"],
    )

    svc._get_payload_name.assert_awaited_once_with("file", "file-1")
    svc.reindex_payload.assert_awaited_once_with("file", "file-1", ["topic-a", "topic-b"])
    assert response.payload_type == "file"
    assert response.payload_id == "file-1"
    assert response.name == "Quy chế đào tạo"
    assert response.node_keys == ["topic-a", "topic-b"]


@pytest.mark.asyncio
async def test_unindex_file_and_faq():
    svc = CorpusService()
    
    mock_repo = MagicMock()
    node = MagicMock(spec=CorpusNodeDocument)
    node.node_key = "topic1"
    mock_repo.get_nodes_containing_payload = AsyncMock(return_value=[node])
    mock_repo.remove_payload_link = AsyncMock()
    svc._repo = mock_repo

    await svc.unindex_file("file123")
    mock_repo.remove_payload_link.assert_called_once_with("topic1", "file", "file123")

    mock_repo.remove_payload_link.reset_mock()
    await svc.unindex_faq("faq123")
    mock_repo.remove_payload_link.assert_called_once_with("topic1", "faq", "faq123")


@pytest.mark.asyncio
async def test_integrity_validator_detects_stale_subtree_and_parent_mismatch():
    root = _node("root", files=["f1"], children=["child"])
    root.subtree_file_ids = []
    root.subtree_faq_ids = []
    root.file_count = 0
    root.faq_count = 0
    child = _node("child", files=["f2"], parent="wrong-parent")
    child.subtree_file_ids = ["f2"]
    child.subtree_faq_ids = []
    child.file_count = 1
    child.faq_count = 0

    repo = CorpusNodeRepository()
    repo.get_all = AsyncMock(return_value=[root, child])
    report = await repo.validate_integrity()

    assert not report.valid
    assert any("direct_file_ids" in error for error in report.errors)
    assert any("mismatched parent" in error for error in report.errors)
