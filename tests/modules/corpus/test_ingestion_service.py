from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.rag.ingestion.ingestion_service import FileIngestionResult, IngestionService


def _service():
    svc = IngestionService.__new__(IngestionService)
    svc._document_parser = MagicMock()
    svc._document_parser.cleanup_local_artifacts = AsyncMock()
    svc._toc_repo = MagicMock()
    svc._toc_repo.upsert_by_file_id = AsyncMock(return_value=True)
    svc._toc_repo.delete_by_file_id = AsyncMock(return_value=True)
    svc._corpus_linker = MagicMock()
    svc._corpus_linker.index_file = AsyncMock(return_value=["topic-1"])
    svc._corpus_linker.unindex_file = AsyncMock()
    return svc


@pytest.mark.asyncio
async def test_ingest_file_uploads_markdown_persists_toc_and_links_corpus():
    svc = _service()
    svc._document_parser.ingest_file = AsyncMock(return_value={
        "markdown_content": "# Nội dung",
        "summary": "Mô tả",
        "line_count": 12,
        "toc_structure": [{"title": "Mục 1", "node_id": "n1", "line_num": 1, "nodes": []}],
        "table_of_contents": ["Mục 1", "Mục 2"],
    })

    with patch("app.modules.rag.ingestion.ingestion_service.r2_storage") as storage:
        storage.upload_file = AsyncMock()
        result = await svc.ingest_file(
            file_id="file1",
            display_name="Tài liệu",
            file_path="/tmp/file.pdf",
            original_storage_path="uploads/file.pdf",
        )

    assert result == FileIngestionResult(
        markdown_storage_path="uploads/file.md",
        markdown_file_size=len("# Nội dung".encode("utf-8")),
        table_of_contents=["Mục 1", "Mục 2"],
        summary="Mô tả",
        line_count=12,
        topic_keys=["topic-1"],
    )
    svc._document_parser.ingest_file.assert_awaited_once_with(
        file_id="file1",
        file_name="Tài liệu",
        file_path="/tmp/file.pdf",
    )
    upload_kwargs = storage.upload_file.await_args.kwargs
    assert upload_kwargs["file"].getvalue() == b"# N\xe1\xbb\x99i dung"
    assert upload_kwargs["object_name"] == "uploads/file.md"
    assert upload_kwargs["content_type"] == "text/markdown; charset=utf-8"

    toc_args = svc._toc_repo.upsert_by_file_id.await_args.args
    assert toc_args[0] == "file1"
    assert toc_args[1].doc_name == "Tài liệu"
    assert toc_args[1].doc_description == "Mô tả"
    assert toc_args[1].line_count == 12
    assert toc_args[1].structure[0].model_dump(mode="json") == {
        "title": "Mục 1",
        "node_id": "n1",
        "line_num": 1,
        "text": None,
        "summary": None,
        "prefix_summary": None,
        "nodes": [],
    }
    assert toc_args[1].markdown_storage_path == "uploads/file.md"

    svc._corpus_linker.index_file.assert_awaited_once_with(
        "file1",
        display_name="Tài liệu",
        doc_description="Mô tả",
        toc_headings=["Mục 1", "Mục 2"],
    )
    svc._document_parser.cleanup_local_artifacts.assert_awaited_once_with("file1")


@pytest.mark.asyncio
async def test_ingest_file_raises_when_corpus_assigns_no_topic():
    svc = _service()
    svc._document_parser.ingest_file = AsyncMock(return_value={
        "markdown_content": "# Nội dung",
        "summary": "Mô tả",
        "line_count": 1,
        "toc_structure": [],
        "table_of_contents": [],
    })
    svc._corpus_linker.index_file = AsyncMock(return_value=[])

    with patch("app.modules.rag.ingestion.ingestion_service.r2_storage") as storage:
        storage.upload_file = AsyncMock()
        with pytest.raises(ValueError, match="could not assign"):
            await svc.ingest_file(
                file_id="file1",
                display_name="Tài liệu",
                file_path="/tmp/file.pdf",
                original_storage_path="uploads/file.pdf",
            )

    svc._document_parser.cleanup_local_artifacts.assert_awaited_once_with("file1")


@pytest.mark.asyncio
async def test_cleanup_file_artifacts_is_best_effort():
    svc = _service()
    svc._toc_repo.delete_by_file_id = AsyncMock(side_effect=RuntimeError("toc down"))
    svc._corpus_linker.unindex_file = AsyncMock(side_effect=RuntimeError("corpus down"))
    svc._document_parser.cleanup_local_artifacts = AsyncMock(side_effect=RuntimeError("local down"))

    with patch("app.modules.rag.ingestion.ingestion_service.r2_storage") as storage:
        storage.delete_file = AsyncMock(side_effect=RuntimeError("storage down"))
        await svc.cleanup_file_artifacts("file1", "uploads/file.md")

    storage.delete_file.assert_awaited_once_with("uploads/file.md")
    svc._toc_repo.delete_by_file_id.assert_awaited_once_with("file1")
    svc._corpus_linker.unindex_file.assert_awaited_once_with("file1")
    svc._document_parser.cleanup_local_artifacts.assert_awaited_once_with("file1")
