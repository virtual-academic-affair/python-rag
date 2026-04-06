"""
RAG Ingest Service (Sprint 3).

Flow:
- Parse PDF via LlamaParse
- Chunk markdown
- Persist chunks to MongoDB
"""

from __future__ import annotations

import hashlib
from typing import Any, Optional

from app.repositories.file_chunk_repository import FileChunkRepository
from app.services.rag.chunking_service import get_chunking_service
from app.services.rag.llamaparse_ingest_service import get_llamaparse_ingest_service


class RagIngestService:
    def __init__(self):
        self._chunk_repo: Optional[FileChunkRepository] = None
        self._parser = get_llamaparse_ingest_service()
        self._chunker = get_chunking_service()

    @property
    def chunk_repo(self) -> FileChunkRepository:
        if self._chunk_repo is None:
            self._chunk_repo = FileChunkRepository()
        return self._chunk_repo

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
        pages = await self._parser.parse_pdf_to_markdown(file_path)
        chunks = self._chunker.chunk_markdown_pages(
            pages,
            chunk_size_chars=chunk_size_chars,
            chunk_overlap_chars=chunk_overlap_chars,
        )

        # idempotent: clear previous chunks
        deleted_mongo = await self.chunk_repo.delete_by_file_id(file_id)

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
                    "page_index_start": c.page_index_start,
                    "page_index_end": c.page_index_end,
                    "section_path": c.section_path,
                    "metadata": metadata or {},
                }
            )

        inserted_count = await self.chunk_repo.create_many(chunk_docs)

        return {
            "file_id": file_id,
            "page_count": len(pages),
            "chunk_count": len(chunks),
            "inserted_count": inserted_count,
            "deleted_previous_mongo": deleted_mongo,
        }

    @staticmethod
    def _build_chunk_id(file_id: str, chunk_index: int, text: str) -> str:
        digest = hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest()[:12]
        return f"{file_id}:{chunk_index}:{digest}"


_rag_ingest_service_instance: Optional[RagIngestService] = None


def get_rag_ingest_service() -> RagIngestService:
    global _rag_ingest_service_instance
    if _rag_ingest_service_instance is None:
        _rag_ingest_service_instance = RagIngestService()
    return _rag_ingest_service_instance

