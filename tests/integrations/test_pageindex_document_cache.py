import io
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.integrations.pageindex.client import PageIndexClient


def _metadata():
    return {
        "id": "doc-1",
        "type": "md",
        "path": "/transient/ignored.md",
        "doc_name": "Document",
        "doc_description": "Description",
        "line_count": 2,
        "structure": [{"title": "Section", "node_id": "1", "line_num": 1, "nodes": []}],
        "markdown_storage_path": "markdown/doc-1.md",
    }


@pytest.mark.asyncio
async def test_get_document_structure_uses_metadata_only(tmp_path):
    client = PageIndexClient(workspace=str(tmp_path))
    client._get_doc_from_cache = AsyncMock(return_value=_metadata())

    with patch(
        "app.integrations.pageindex.client.r2_storage.download_file",
        AsyncMock(side_effect=AssertionError("R2 must not be touched")),
    ) as download:
        result = await client.get_document_structure("doc-1")

    assert "Section" in result
    download.assert_not_awaited()
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_legacy_metadata_without_storage_path_reloads_from_mongo(tmp_path):
    client = PageIndexClient(workspace=str(tmp_path))
    client._get_doc_from_cache = AsyncMock(return_value={
        "doc_name": "Legacy",
        "doc_description": "",
        "line_count": 1,
        "structure": [],
    })
    client._save_doc_to_cache = AsyncMock()
    client._toc_repo = SimpleNamespace(find_by_file_id=AsyncMock(return_value=SimpleNamespace(
        doc_name="Reloaded",
        doc_description="Description",
        line_count=4,
        structure=[],
        markdown_storage_path="markdown/doc-1.md",
    )))

    doc = await client._load_document_metadata("doc-1")

    assert doc["doc_name"] == "Reloaded"
    assert doc["path"] == str(tmp_path / "doc-1.md")
    client._toc_repo.find_by_file_id.assert_awaited_once_with("doc-1")
    client._save_doc_to_cache.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_page_content_downloads_once_then_reuses_local_markdown(tmp_path):
    client = PageIndexClient(workspace=str(tmp_path))
    client._get_doc_from_cache = AsyncMock(return_value=_metadata())
    download = AsyncMock(return_value=io.BytesIO(b"# Section\nBody\n"))

    with patch("app.integrations.pageindex.client.r2_storage.download_file", download):
        first = await client.get_page_content("doc-1", "1-2")
        second = await client.get_page_content("doc-1", "1-2")

    assert "Section" in first
    assert first == second
    download.assert_awaited_once_with("markdown/doc-1.md")
    assert (tmp_path / "doc-1.md").read_bytes() == b"# Section\nBody\n"


@pytest.mark.asyncio
async def test_index_md_content_does_not_cache_transient_ingestion_path(tmp_path):
    md_path = tmp_path / "transient.md"
    md_path.write_text("# Heading\n", encoding="utf-8")
    client = PageIndexClient(workspace=str(tmp_path))
    client._save_doc_to_cache = AsyncMock()

    with patch(
        "app.integrations.pageindex.client.md_to_tree",
        AsyncMock(return_value={
            "doc_name": "Generated",
            "doc_description": "Summary",
            "line_count": 1,
            "structure": [],
        }),
    ):
        await client.index_md_content(str(md_path), "doc-1", "Document")

    client._save_doc_to_cache.assert_not_awaited()
