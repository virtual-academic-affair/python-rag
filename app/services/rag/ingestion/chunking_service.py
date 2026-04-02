"""
Custom chunking service for regulation-like documents.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class ChunkItem:
    chunk_id: str
    text: str
    section_path: str


class ChunkingService:
    """Simple heading-aware chunking for Sprint 1."""

    _section_pattern = re.compile(r"^(điều|khoản|mục|chương)\s+", re.IGNORECASE)

    def chunk_markdown(self, markdown_text: str, file_id: str) -> list[ChunkItem]:
        lines = [ln.rstrip() for ln in markdown_text.splitlines()]
        chunks: list[ChunkItem] = []

        current_heading = "ROOT"
        current_buffer: list[str] = []
        idx = 0

        def flush() -> None:
            nonlocal idx, current_buffer
            text = "\n".join([ln for ln in current_buffer if ln.strip()]).strip()
            if not text:
                return
            idx += 1
            chunks.append(
                ChunkItem(
                    chunk_id=f"{file_id}_chunk_{idx}",
                    text=text,
                    section_path=current_heading,
                )
            )
            current_buffer = []

        for line in lines:
            if self._section_pattern.search(line.strip()):
                flush()
                current_heading = line.strip()
                current_buffer.append(line)
            else:
                current_buffer.append(line)

            if len("\n".join(current_buffer)) > 1200:
                flush()

        flush()
        return chunks


chunking_service = ChunkingService()

