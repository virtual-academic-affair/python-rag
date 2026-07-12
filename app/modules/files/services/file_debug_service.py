"""Debug/preview file workflows."""

from __future__ import annotations

import logging
import os
import tempfile

from fastapi import HTTPException, UploadFile, status

from app.integrations.llamaparse.client import get_llamaparse_client
from app.modules.files.dtos import FileParsePreviewPage, FileParsePreviewResponse

logger = logging.getLogger(__name__)


class FileDebugService:
    async def parse_pdf_preview(self, file: UploadFile) -> FileParsePreviewResponse:
        temp_file_path = None
        try:
            if not file.filename.lower().endswith(".pdf"):
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only .pdf files are supported")

            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf", mode="wb") as temp_file:
                contents = await file.read()
                temp_file.write(contents)
                temp_file_path = temp_file.name

            parser_svc = get_llamaparse_client()
            pages = await parser_svc.parse_pdf_to_markdown(temp_file_path)
            return FileParsePreviewResponse(
                filename=file.filename,
                page_count=len(pages),
                pages=[FileParsePreviewPage(page_index=page.page_index, markdown=page.markdown) for page in pages],
            )
        finally:
            if temp_file_path and os.path.exists(temp_file_path):
                try:
                    os.unlink(temp_file_path)
                except Exception as cleanup_error:
                    logger.warning("Failed to cleanup parse-preview temp file: %s", cleanup_error)


_file_debug_service_instance: FileDebugService | None = None


def get_file_debug_service() -> FileDebugService:
    global _file_debug_service_instance
    if _file_debug_service_instance is None:
        _file_debug_service_instance = FileDebugService()
    return _file_debug_service_instance
