from __future__ import annotations

from dataclasses import dataclass
import io
import logging

from app.integrations.storage.client import r2_storage
from app.modules.rag.ingestion.corpus_linker import get_corpus_linker
from app.modules.rag.ingestion.document_parser import get_document_parser

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FileIngestionResult:
    markdown_storage_path: str
    markdown_file_size: int
    table_of_contents: list[str]
    summary: str
    line_count: int
    node_keys: list[str]


class IngestionService:
    """Orchestrates file ingestion artifacts for RAG."""

    def __init__(self):
        from app.modules.files.toc_tree.repositories.toc_tree_repository import FileTocTreeRepository

        self._document_parser = get_document_parser()
        self._toc_repo = FileTocTreeRepository()
        self._corpus_linker = get_corpus_linker()

    async def ingest_file(
        self,
        *,
        file_id: str,
        display_name: str,
        file_path: str,
        original_storage_path: str,
    ) -> FileIngestionResult:
        from app.modules.files.toc_tree.models.toc_tree import TocTreeUpsertData

        markdown_storage_path = original_storage_path.rsplit(".", 1)[0] + ".md"

        try:
            ingest_result = await self._document_parser.ingest_file(
                file_id=file_id,
                file_name=display_name,
                file_path=file_path,
            )

            markdown_content = ingest_result["markdown_content"]
            markdown_bytes = markdown_content.encode("utf-8")

            await r2_storage.upload_file(
                file=io.BytesIO(markdown_bytes),
                object_name=markdown_storage_path,
                content_type="text/markdown; charset=utf-8",
            )

            await self._toc_repo.upsert_by_file_id(
                file_id,
                TocTreeUpsertData(
                    doc_name=display_name,
                    doc_description=ingest_result.get("summary", ""),
                    line_count=ingest_result.get("line_count", 0),
                    structure=ingest_result.get("toc_structure", []),
                    markdown_storage_path=markdown_storage_path,
                ),
            )

            logger.info(f"[Corpus] Bắt đầu index file {file_id} ('{display_name}') vào corpus tree")
            node_keys = await self._corpus_linker.index_file(
                file_id,
                display_name=display_name,
                doc_description=ingest_result.get("summary", "") or "",
                toc_headings=ingest_result.get("table_of_contents", []),
            )
            if not node_keys:
                raise ValueError("LLM could not assign the file to any node in the corpus catalog.")

            logger.info(
                f"[Corpus] Index file {file_id} xong — gán vào {len(node_keys)} node: {node_keys}"
            )

            return FileIngestionResult(
                markdown_storage_path=markdown_storage_path,
                markdown_file_size=len(markdown_bytes),
                table_of_contents=ingest_result.get("table_of_contents", []),
                summary=ingest_result.get("summary", ""),
                line_count=ingest_result.get("line_count", 0),
                node_keys=node_keys,
            )
        finally:
            await self._cleanup_local_artifacts(file_id)

    async def cleanup_file_artifacts(
        self,
        file_id: str,
        markdown_storage_path: str | None = None,
    ) -> None:
        """Best-effort cleanup for artifacts created before ingestion failure."""
        if markdown_storage_path:
            try:
                await r2_storage.delete_file(markdown_storage_path)
            except Exception as e:
                logger.warning(f"Failed to cleanup markdown artifact for failed file {file_id}: {e}")

        try:
            await self._toc_repo.delete_by_file_id(file_id)
        except Exception as e:
            logger.warning(f"Failed to cleanup TOC for failed file {file_id}: {e}")

        try:
            await self._corpus_linker.unindex_file(file_id)
        except Exception as e:
            logger.warning(f"Failed to cleanup corpus index for failed file {file_id}: {e}")

        await self._cleanup_local_artifacts(file_id)

    async def _cleanup_local_artifacts(self, file_id: str) -> None:
        try:
            await self._document_parser.cleanup_local_artifacts(file_id)
        except Exception as e:
            logger.warning(f"Failed to cleanup markdown artifacts for {file_id}: {e}")


_ingestion_service_instance: IngestionService | None = None


def get_ingestion_service() -> IngestionService:
    global _ingestion_service_instance
    if _ingestion_service_instance is None:
        _ingestion_service_instance = IngestionService()
    return _ingestion_service_instance
