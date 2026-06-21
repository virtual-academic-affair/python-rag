"""
RAG Ingestion Service.

Flow:
- Parse PDF via LlamaParse
- Chunk markdown
- Embed chunks via Gemini + index into Qdrant
- Persist chunks to MongoDB
"""

from __future__ import annotations
import asyncio
import hashlib
import time
from pathlib import Path
from typing import Any, Optional

import logging

from app.modules.files.toc_tree.repositories.toc_tree_repository import FileTocTreeRepository
from app.modules.rag.ingestion.chunking_service import get_chunking_service
from app.integrations.llamaparse.client import get_llamaparse_client
from app.integrations.qdrant.indexer import get_qdrant_indexer
from app.integrations.pageindex.client import get_page_index_client
from app.core.config import settings

logger = logging.getLogger(__name__)

class IngestionService:
    def __init__(self):
        self._toc_repo: Optional[FileTocTreeRepository] = None
        self._parser = get_llamaparse_client()
        self._chunker = get_chunking_service()
        self._indexer = get_qdrant_indexer()
        self._page_index = get_page_index_client()

    @property
    def toc_repo(self) -> FileTocTreeRepository:
        if self._toc_repo is None:
            self._toc_repo = FileTocTreeRepository()
        return self._toc_repo

    async def ingest_file(
        self,
        *,
        file_id: str,
        file_name: str,
        file_path: str,
        metadata: Optional[dict[str, Any]] = None,
        chunk_size_chars: int = 1800,
        chunk_overlap_chars: int = 250,
    ) -> dict[str, Any]:
        """Ingest a file (PDF, TXT, MD) by parsing/reading, chunking, embedding, and storing."""
        start_total = time.perf_counter()
        
        # 1. Parse content to Markdown via LlamaParse
        start_parse = time.perf_counter()
        pages = await self._parser.parse_pdf_to_markdown(file_path)
        markdown_content = "\n\n".join(p.markdown for p in pages if p.markdown)
            
        parse_dur = time.perf_counter() - start_parse
        logger.info(f"[Ingestion] Phase 1: Content extraction completed in {parse_dur:.2f}s")

        # 2 & 3. Run TOC Generation and Qdrant Indexing in parallel
        logger.info(f"[Ingestion] Phase 2 & 3: Running TOC Generation and Qdrant Indexing in parallel...")
        start_parallel = time.perf_counter()
        
        toc_task = self._build_toc(file_id, file_name, markdown_content)
        index_task = self._chunk_and_index(
            file_id, file_name, pages, metadata, chunk_size_chars, chunk_overlap_chars
        )
        
        toc_result, (chunk_count, indexed_count) = await asyncio.gather(toc_task, index_task)
        
        parallel_dur = time.perf_counter() - start_parallel
        logger.info(f"[Ingestion] Parallel processing (TOC + Indexing) completed in {parallel_dur:.2f}s")
        
        total_dur = time.perf_counter() - start_total
        logger.info(f"[Ingestion] Total ingestion for file {file_id} completed in {total_dur:.2f}s")

        return {
            "file_id": file_id,
            "page_count": len(pages),
            "chunk_count": chunk_count,
            "indexed_count": indexed_count,
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
            table_of_contents = []
            summary = None
            toc_structure = []

        return {
            "table_of_contents": table_of_contents,
            "summary": summary,
            "toc_structure": toc_structure,
            "line_count": toc_line_count,
        }

    async def _chunk_and_index(
        self,
        file_id: str,
        file_name: str,
        pages: list,
        metadata: Optional[dict[str, Any]],
        chunk_size_chars: int,
        chunk_overlap_chars: int,
    ) -> tuple[int, int]:
        """Chunk markdown pages and index them to Qdrant."""
        chunks = self._chunker.chunk_markdown_pages(
            pages,
            chunk_size_chars=chunk_size_chars,
            chunk_overlap_chars=chunk_overlap_chars,
        )

        await self._indexer.delete_by_file_id(file_id)

        chunk_docs: list[dict[str, Any]] = []
        for c in chunks:
            chunk_id = self._build_chunk_id(file_id=file_id, chunk_index=c.chunk_index, text=c.text)
            chunk_docs.append(
                {
                    "chunk_id": chunk_id,
                    "file_id": file_id,
                    "file_name": file_name,
                    "chunk_index": c.chunk_index,
                    "text": c.text,
                    "section_path": c.section_path,
                    "metadata": metadata or {},
                }
            )

        if chunk_docs:
            indexed_count = await self._indexer.ingest_chunks(chunk_docs)
        else:
            indexed_count = 0

        return len(chunks), indexed_count
    
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
        """Flatten PageIndex tree structure into a simple list of headings.
        
        Loại bỏ các tiêu đề header/footer phổ biến của văn bản hành chính VN
        (tên trường, quốc hiệu, tiêu ngữ...) vì chúng không có giá trị tra cứu.
        """
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



    @staticmethod
    def _build_chunk_id(file_id: str, chunk_index: int, text: str) -> str:
        digest = hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest()[:12]
        return f"{file_id}:{chunk_index}:{digest}"


_ingestion_service_instance: Optional[IngestionService] = None

def get_ingestion_service() -> IngestionService:
    global _ingestion_service_instance
    if _ingestion_service_instance is None:
        _ingestion_service_instance = IngestionService()
    return _ingestion_service_instance
