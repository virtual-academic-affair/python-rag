"""
Document parser for the RAG ingestion flow.

Flow:
- Parse PDF via LlamaParse
- Build TOC/summary tree via PageIndex
"""

from __future__ import annotations
import asyncio
import time
from pathlib import Path
from typing import Any

import logging

from app.integrations.llamaparse.client import get_llamaparse_client
from app.core.config import settings

logger = logging.getLogger(__name__)

class DocumentParser:
    def __init__(self):
        from app.integrations.pageindex.client import get_page_index_client

        self._parser = get_llamaparse_client()
        self._page_index = get_page_index_client()

    async def ingest_file(
        self,
        *,
        file_id: str,
        file_name: str,
        file_path: str,
    ) -> dict[str, Any]:
        """Ingest a file: parse to Markdown then build TOC/summary via PageIndex."""
        start_total = time.perf_counter()

        # 1. Parse content to Markdown via LlamaParse
        start_parse = time.perf_counter()
        pages = await self._parser.parse_pdf_to_markdown(file_path)
        markdown_content = "\n\n".join(p.markdown for p in pages if p.markdown)
        parse_dur = time.perf_counter() - start_parse
        logger.info(f"[Ingestion] Phase 1: Content extraction completed in {parse_dur:.2f}s")

        # 2. Build TOC/summary via PageIndex
        logger.info(f"[Ingestion] Phase 2: Building TOC/summary via PageIndex...")
        toc_result = await self._build_toc(file_id, file_name, markdown_content)

        total_dur = time.perf_counter() - start_total
        logger.info(f"[Ingestion] Total ingestion for file {file_id} completed in {total_dur:.2f}s")

        return {
            "file_id": file_id,
            "page_count": len(pages),
            "markdown_content": markdown_content,
            "table_of_contents": toc_result["table_of_contents"],
            "summary": toc_result["summary"],
            "toc_structure": toc_result["toc_structure"],
            "line_count": toc_result["line_count"],
        }

    async def _build_toc(self, file_id: str, file_name: str, markdown_content: str) -> dict[str, Any]:
        """Generate TOC and Summary using PageIndex."""
        workspace_dir = Path(settings.PAGEINDEX_WORKSPACE).resolve()
        workspace_dir.mkdir(parents=True, exist_ok=True)
        md_file_path = workspace_dir / f"{file_id}.md"

        def _write_md():
            with open(md_file_path, "w", encoding="utf-8") as f:
                f.write(markdown_content)

        await asyncio.to_thread(_write_md)

        toc_line_count = 0
        try:
            toc_result = await self._page_index.index_md_content(
                md_path=str(md_file_path),
                doc_id=file_id,
                doc_name=file_name
            )

            table_of_contents = self._extract_flat_toc(toc_result["structure"])
            summary = toc_result["doc_description"]
            toc_structure = toc_result["structure"]
            toc_line_count = toc_result.get("line_count", 0)
        except Exception as e:
            logger.error(f"PageIndex failed to generate TOC/Summary for {file_id}: {e}")
            raise

        return {
            "table_of_contents": table_of_contents,
            "summary": summary,
            "toc_structure": toc_structure,
            "line_count": toc_line_count,
        }

    # Các tiêu đề header/footer phổ biến của văn bản hành chính VN — không có giá trị tra cứu
    _BLACKLISTED_TOC_ENTRIES = {
        "đại học quốc gia tp. hcm",
        "đại học quốc gia tp.hcm",
        "đại học quốc gia thành phố hồ chí minh",
        "cộng hòa xã hội chủ nghĩa việt nam",
        "trường đại học khoa học tự nhiên",
        "độc lập tự do hạnh phúc",
        "độc lập - tự do - hạnh phúc",
        "trường đh khoa học tự nhiên",
        "đhqg-hcm",
        "đhqg tp.hcm",
        "đhqg tp. hcm",
    }

    def _extract_flat_toc(self, structure: list[dict[str, Any]]) -> list[str]:
        """Flatten PageIndex tree structure into a simple list of headings."""
        toc = []

        def _is_blacklisted(title: str) -> bool:
            normalized = " ".join(title.lower().split())
            return normalized in self._BLACKLISTED_TOC_ENTRIES

        def traverse(nodes):
            for node in nodes:
                title = node.get("title")
                if title and not _is_blacklisted(title):
                    toc.append(title)
                if node.get("nodes"):
                    traverse(node["nodes"])

        traverse(structure)
        return toc

    async def cleanup_local_artifacts(self, file_id: str):
        """Delete local markdown file after ingestion."""
        workspace_dir = Path(settings.PAGEINDEX_WORKSPACE).resolve()
        md_file_path = workspace_dir / f"{file_id}.md"
        if md_file_path.exists():
            md_file_path.unlink()
            logger.info(f"Cleaned up local markdown artifact: {md_file_path}")


_document_parser_instance: DocumentParser | None = None

def get_document_parser() -> DocumentParser:
    global _document_parser_instance
    if _document_parser_instance is None:
        _document_parser_instance = DocumentParser()
    return _document_parser_instance
