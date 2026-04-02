"""
LlamaIndex-based parser service.
Sprint 1: parse file into markdown-like text.
"""

from __future__ import annotations

import os
from llama_index.core import SimpleDirectoryReader


class LlamaParserService:
    """Parse local files to plain text/markdown-like content."""

    def parse_to_markdown(self, file_path: str) -> str:
        file_dir = os.path.dirname(file_path) or "."
        file_name = os.path.basename(file_path)

        reader = SimpleDirectoryReader(
            input_dir=file_dir,
            input_files=[file_path],
            recursive=False,
            required_exts=[os.path.splitext(file_name)[1]] if os.path.splitext(file_name)[1] else None,
        )
        docs = reader.load_data()
        if not docs:
            return ""

        # Sprint 1: merge raw extracted text
        return "\n\n".join((d.text or "") for d in docs).strip()


llama_parser_service = LlamaParserService()

