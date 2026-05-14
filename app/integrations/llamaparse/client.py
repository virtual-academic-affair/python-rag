"""
LlamaParse Ingest Service (Sprint 1).

Scope of Sprint 1:
- Parse PDF to markdown using LlamaParse Cloud.
- Return page-level markdown blocks with lightweight normalization.
- No indexing (Qdrant/ES) yet.
"""

from __future__ import annotations

import logging
import asyncio
from llama_parse import LlamaParse
from dataclasses import dataclass
from typing import Any, Optional

from app.core.config import settings
from app.core.exceptions import ValidationException, ExternalServiceException

logger = logging.getLogger(__name__)


@dataclass
class ParsedMarkdownPage:
    """One parsed markdown block (usually page-level) from LlamaParse."""

    page_index: int
    markdown: str
    metadata: dict[str, Any]


class LlamaParseClient:
    """Service that wraps LlamaParse Cloud parsing for PDF input.
    
    Hỗ trợ cả PDF thường và PDF dạng ảnh scan thông qua chế độ premium_mode
    của LlamaParse (sử dụng multimodal OCR để trích xuất text từ ảnh scan).
    """

    async def parse_pdf_to_markdown(self, file_path: str) -> list[ParsedMarkdownPage]:
        """
        Parse a PDF file and return normalized markdown blocks.

        - Bật premium_mode để LlamaParse tự động OCR các trang scan.
        - Cảnh báo nếu trang trả về nội dung trống (có thể do scan chất lượng kém).

        Raises:
            ValidationException: if API key is missing or parse fails.
        """
        if not settings.LLAMA_CLOUD_API_KEY:
            raise ValidationException(
                "LLAMA_CLOUD_API_KEY is not configured. Please set it in environment to use LlamaParse."
            )

        parser = LlamaParse(
            api_key=settings.LLAMA_CLOUD_API_KEY,
            result_type=settings.LLAMA_PARSE_RESULT_TYPE,
            language=settings.LLAMA_PARSE_LANGUAGE,
            # Nếu bật premium_mode=True, LlamaParse sẽ ép dùng Multimodal OCR cho mọi trang.
            # Nếu tắt, dùng auto_mode=True để hệ thống tự phát hiện trang nào cần OCR (tiết kiệm hơn).
            premium_mode=settings.LLAMA_PARSE_USE_PREMIUM,
            auto_mode=not settings.LLAMA_PARSE_USE_PREMIUM,
        )

        logger.info(
            "LlamaParse: parsing file %s (premium_mode=%s, auto_mode=%s)", 
            file_path, settings.LLAMA_PARSE_USE_PREMIUM, not settings.LLAMA_PARSE_USE_PREMIUM
        )

        try:
            documents = await asyncio.wait_for(
                parser.aload_data(file_path),
                timeout=600.0
            )
        except asyncio.TimeoutError:
            logger.error("LlamaParse parse timeout for file %s", file_path)
            raise ExternalServiceException(f"LlamaParse timeout: failed to parse PDF {file_path} within 600s")
        except Exception as exc:
            logger.error("LlamaParse parse failed: %s", exc, exc_info=True)
            raise ExternalServiceException(f"LlamaParse failed to parse PDF: {exc}") from exc

        pages: list[ParsedMarkdownPage] = []
        empty_page_count = 0
        for i, doc in enumerate(documents):
            metadata = getattr(doc, "metadata", {}) or {}
            raw_text = getattr(doc, "text", "") or ""
            normalized_text = self._normalize_markdown(raw_text)

            page_index = self._extract_page_index(metadata, default=i + 1)

            # Cảnh báo nếu trang trả về trống — thường gặp khi file scan chất
            # lượng quá thấp hoặc trang chỉ chứa ảnh mà OCR không nhận ra được.
            if not normalized_text.strip():
                empty_page_count += 1
                logger.warning(
                    "LlamaParse: page %d of %s returned empty content (possible low-quality scan)",
                    page_index, file_path
                )
            
            pages.append(
                ParsedMarkdownPage(
                    page_index=page_index,
                    markdown=normalized_text,
                    metadata=metadata,
                )
            )

        if not pages:
            raise ValidationException("LlamaParse returned empty result for this PDF.")

        if empty_page_count > 0:
            logger.warning(
                "LlamaParse: %d/%d pages returned empty content for %s. "
                "File may be a low-quality scanned PDF.",
                empty_page_count, len(pages), file_path
            )

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


_llamaparse_client_instance: Optional[LlamaParseClient] = None


def get_llamaparse_client() -> LlamaParseClient:
    """Singleton accessor for dependency injection / service reuse."""
    global _llamaparse_client_instance
    if _llamaparse_client_instance is None:
        _llamaparse_client_instance = LlamaParseClient()
    return _llamaparse_client_instance
