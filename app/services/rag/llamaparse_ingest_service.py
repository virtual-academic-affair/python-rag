"""
LlamaParse Ingest Service (Sprint 1).

Scope of Sprint 1:
- Parse PDF to markdown using LlamaParse Cloud.
- Return page-level markdown blocks with lightweight normalization.
- No indexing (Qdrant/ES) yet.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

from app.core.config import settings
from app.core.exceptions import ValidationException

logger = logging.getLogger(__name__)


@dataclass
class ParsedMarkdownPage:
    """One parsed markdown block (usually page-level) from LlamaParse."""

    page_index: int
    markdown: str
    metadata: dict[str, Any]


class LlamaParseIngestService:
    """Service that wraps LlamaParse Cloud parsing for PDF input."""

    async def parse_pdf_to_markdown(self, file_path: str) -> list[ParsedMarkdownPage]:
        """
        Parse a PDF file and return normalized markdown blocks.

        Raises:
            ValidationException: if API key is missing or parse fails.
        """
        if not settings.LLAMA_CLOUD_API_KEY:
            raise ValidationException(
                "LLAMA_CLOUD_API_KEY is not configured. Please set it in environment to use LlamaParse."
            )

        try:
            from llama_parse import LlamaParse
        except Exception as exc:  # pragma: no cover - import/runtime env issue
            raise ValidationException(
                "llama-parse package is not installed or cannot be imported."
            ) from exc

        parser = LlamaParse(
            api_key=settings.LLAMA_CLOUD_API_KEY,
            result_type=settings.LLAMA_PARSE_RESULT_TYPE,
            language=settings.LLAMA_PARSE_LANGUAGE,
        )

        logger.info("LlamaParse: parsing file %s", file_path)

        try:
            documents = await parser.aload_data(file_path)
        except Exception as exc:
            logger.error("LlamaParse parse failed: %s", exc, exc_info=True)
            raise ValidationException(f"LlamaParse failed to parse PDF: {exc}") from exc

        pages: list[ParsedMarkdownPage] = []
        for i, doc in enumerate(documents):
            metadata = getattr(doc, "metadata", {}) or {}
            raw_text = getattr(doc, "text", "") or ""
            normalized_text = self._normalize_markdown(raw_text)

            page_index = self._extract_page_index(metadata, default=i + 1)

            pages.append(
                ParsedMarkdownPage(
                    page_index=page_index,
                    markdown=normalized_text,
                    metadata=metadata,
                )
            )

        if not pages:
            raise ValidationException("LlamaParse returned empty result for this PDF.")

        pages.sort(key=lambda p: p.page_index)
        return pages

    @staticmethod
    def _extract_page_index(metadata: dict[str, Any], default: int) -> int:
        """Extract page index from metadata with safe fallback."""
        candidates = (
            metadata.get("page_number"),
            metadata.get("page"),
            metadata.get("page_index"),
        )
        for value in candidates:
            try:
                if value is not None:
                    return int(value)
            except (TypeError, ValueError):
                continue
        return default

    @staticmethod
    def _normalize_markdown(text: str) -> str:
        """Light markdown normalization for stable downstream chunking."""
        normalized_lines: list[str] = []
        prev_blank = False

        for line in text.splitlines():
            clean = line.rstrip()
            is_blank = clean == ""
            if is_blank and prev_blank:
                continue
            normalized_lines.append(clean)
            prev_blank = is_blank

        return "\n".join(normalized_lines).strip()


_llamaparse_ingest_service_instance: Optional[LlamaParseIngestService] = None


def get_llamaparse_ingest_service() -> LlamaParseIngestService:
    """Singleton accessor for dependency injection / service reuse."""
    global _llamaparse_ingest_service_instance
    if _llamaparse_ingest_service_instance is None:
        _llamaparse_ingest_service_instance = LlamaParseIngestService()
    return _llamaparse_ingest_service_instance

