"""
Chunking Service.
Builds semantic chunks from parsed markdown pages.
"""

from __future__ import annotations
from dataclasses import dataclass
import re
from typing import Optional

from app.core.exceptions import ValidationException
from app.integrations.llamaparse.client import ParsedMarkdownPage


@dataclass
class ChunkBlock:
    chunk_index: int
    text: str
    page_index_start: int
    page_index_end: int
    section_path: Optional[str] = None


class ChunkingService:
    """Create chunks from markdown pages for retrieval indexing."""

    def chunk_markdown_pages(
        self,
        pages: list[ParsedMarkdownPage],
        chunk_size_chars: int = 1800,
        chunk_overlap_chars: int = 250,
    ) -> list[ChunkBlock]:
        if not pages:
            return []

        if chunk_size_chars < 400:
            raise ValidationException("chunk_size_chars must be >= 400")
        if chunk_overlap_chars < 0 or chunk_overlap_chars >= chunk_size_chars:
            raise ValidationException("chunk_overlap_chars must be >= 0 and < chunk_size_chars")

        sections = self._split_sections(pages)

        chunks: list[ChunkBlock] = []
        chunk_idx = 0
        for sec in sections:
            text = sec["text"].strip()
            if not text:
                continue

            for part in self._window_split(text, chunk_size_chars, chunk_overlap_chars):
                chunks.append(
                    ChunkBlock(
                        chunk_index=chunk_idx,
                        text=part,
                        page_index_start=sec.get("page_start", 0),
                        page_index_end=sec.get("page_end", 0),
                        section_path=sec.get("section_path"),
                    )
                )
                chunk_idx += 1

        return chunks

    def _split_sections(self, pages: list[ParsedMarkdownPage]) -> list[dict]:
        """Split by markdown headings while preserving page range."""
        sections: list[dict] = []
        current: Optional[dict] = None

        heading_pattern = re.compile(r"^#{1,6}\s+(.+)$")

        for page in pages:
            lines = page.markdown.splitlines()
            for line in lines:
                m = heading_pattern.match(line.strip())
                if m:
                    # flush previous section
                    if current and current["text"].strip():
                        sections.append(current)

                    heading = m.group(1).strip()
                    current = {
                        "section_path": heading,
                        "page_start": page.page_index,
                        "page_end": page.page_index,
                        "text": line.strip() + "\n",
                    }
                else:
                    if current is None:
                        current = {
                            "section_path": None,
                            "page_start": page.page_index,
                            "page_end": page.page_index,
                            "text": "",
                        }
                    current["text"] += line + "\n"
                    current["page_end"] = page.page_index

        if current and current["text"].strip():
            sections.append(current)

        return sections

    @staticmethod
    def _window_split(text: str, size: int, overlap: int) -> list[str]:
        """Simple window split with soft break on line boundary."""
        if len(text) <= size:
            return [text.strip()]

        chunks: list[str] = []
        start = 0
        step = size - overlap

        while start < len(text):
            end = min(start + size, len(text))
            part = text[start:end]

            # try to cut at newline near end for readability
            if end < len(text):
                last_newline = part.rfind("\n")
                if last_newline > int(size * 0.6):
                    end = start + last_newline
                    part = text[start:end]

            chunks.append(part.strip())
            if end >= len(text):
                break
            start = max(end - overlap, start + 1)

        return [c for c in chunks if c]


_chunking_service_instance: Optional[ChunkingService] = None


def get_chunking_service() -> ChunkingService:
    global _chunking_service_instance
    if _chunking_service_instance is None:
        _chunking_service_instance = ChunkingService()
    return _chunking_service_instance
