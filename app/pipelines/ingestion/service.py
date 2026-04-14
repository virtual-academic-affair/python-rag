"""
RAG Ingestion Service.

Flow:
- Parse PDF via LlamaParse
- Chunk markdown
- Embed chunks via Gemini + index into Qdrant
- Persist chunks to MongoDB
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from typing import Any, Optional

import logging

from app.modules.files.toc_tree.repository import FileTocTreeRepository
from app.pipelines.ingestion.chunking import get_chunking_service
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

    async def ingest_pdf_chunks(
        self,
        *,
        file_id: str,
        file_name: str,
        file_path: str,
        metadata: Optional[dict[str, Any]] = None,
        chunk_size_chars: int = 1800,
        chunk_overlap_chars: int = 250,
    ) -> dict[str, Any]:
        """Ingest a PDF file by parsing, chunking, embedding, and storing."""
        pages = await self._parser.parse_pdf_to_markdown(file_path)
        markdown_content = "\n\n".join(p.markdown for p in pages if p.markdown)

        # Generate TOC and Summary using PageIndex
        import pathlib
        workspace_dir = pathlib.Path(settings.PAGEINDEX_WORKSPACE).resolve()
        workspace_dir.mkdir(parents=True, exist_ok=True)
        md_file_path = workspace_dir / f"{file_id}.md"

        with open(md_file_path, "w", encoding="utf-8") as f:
            f.write(markdown_content)
        
        toc_line_count = 0
        try:
            doc_id = file_id 
            
            toc_result = await self._page_index.index_md_content(
                md_path=str(md_file_path),
                doc_id=doc_id,
                doc_name=file_name
            )
            
            # In-memory storage for returning to caller
            table_of_contents = self._extract_flat_toc(toc_result["structure"])
            summary = toc_result["doc_description"]
            toc_structure = toc_result["structure"]
            toc_line_count = toc_result.get("line_count", 0)
        except Exception as e:
            logger.error(f"PageIndex failed to generate TOC/Summary for {file_id}: {e}")
            table_of_contents = []
            summary = None
            toc_structure = []

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

        return {
            "file_id": file_id,
            "page_count": len(pages),
            "chunk_count": len(chunks),
            "indexed_count": indexed_count,
            "markdown_content": markdown_content,
            "table_of_contents": table_of_contents,
            "summary": summary,
            "toc_structure": toc_structure,
            "line_count": toc_line_count,
        }
    
    def _extract_flat_toc(self, structure: list[dict[str, Any]]) -> list[str]:
        """Flatten PageIndex tree structure into a simple list of headings."""
        toc = []
        
        def traverse(nodes):
            for node in nodes:
                title = node.get("title")
                if title:
                    toc.append(title)
                if node.get("nodes"):
                    traverse(node["nodes"])
        
        traverse(structure)
        return toc

    async def cleanup_local_artifacts(self, file_id: str):
        """Delete local markdown file after ingestion."""
        import pathlib
        workspace_dir = pathlib.Path(settings.PAGEINDEX_WORKSPACE).resolve()
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
