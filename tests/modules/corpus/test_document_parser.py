from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.config import settings
from app.modules.rag.ingestion.document_parser import DocumentParser


@pytest.mark.asyncio
async def test_build_toc_raises_when_pageindex_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "PAGEINDEX_WORKSPACE", str(tmp_path))

    parser = DocumentParser.__new__(DocumentParser)
    parser._page_index = MagicMock()
    parser._page_index.index_md_content = AsyncMock(side_effect=RuntimeError("pageindex failed"))

    with pytest.raises(RuntimeError, match="pageindex failed"):
        await parser._build_toc("file1", "Tài liệu", "# Nội dung")
