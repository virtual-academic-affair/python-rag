from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
import tempfile
import os
import logging

from app.modules.files.dtos import (
    FileParsePreviewResponse,
    FileParsePreviewPage,
)
from app.integrations.llamaparse.client import get_llamaparse_client
from app.core.auth import JWTPayload
from app.core.exceptions import AppException
from app.core.dependencies import require_admin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/debug/files", tags=["Debug Files"])

@router.post(
    "/parse-preview",
    response_model=FileParsePreviewResponse,
    summary="Parse PDF to markdown preview",
    description="Parse an uploaded PDF using LlamaParse and return normalized markdown pages.",
)
async def parse_pdf_preview(
    file: UploadFile = File(..., description="PDF file to parse"),
    _admin: JWTPayload = Depends(require_admin),
):
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
            pages=[FileParsePreviewPage(page_index=p.page_index, markdown=p.markdown) for p in pages],
        )
    except HTTPException:
        raise
    except AppException:
        raise
    except Exception as e:
        logger.error(f"Parse preview failed: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
    finally:
        if temp_file_path and os.path.exists(temp_file_path):
            try:
                os.unlink(temp_file_path)
            except Exception as cleanup_error:
                logger.warning(f"Failed to cleanup parse-preview temp file: {cleanup_error}")
