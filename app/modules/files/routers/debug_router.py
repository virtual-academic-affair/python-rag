from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from typing import Dict, Any
import tempfile
import os
import logging

from app.modules.files.dtos import (
    FileParsePreviewResponse,
    FileParsePreviewPage,
    FileChunkPreviewResponse,
    FileChunkPreviewItem,
)
from app.integrations.llamaparse.client import get_llamaparse_client
from app.modules.rag.ingestion.chunking_service import get_chunking_service
from app.core.exceptions import ValidationException
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
    _admin: Dict[str, Any] = Depends(require_admin),
):
    """Preview LlamaParse output before indexing/chunking."""
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
    except ValidationException as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"Parse preview failed: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
    finally:
        if temp_file_path and os.path.exists(temp_file_path):
            try:
                os.unlink(temp_file_path)
            except Exception as cleanup_error:
                logger.warning(f"Failed to cleanup parse-preview temp file: {cleanup_error}")


@router.post(
    "/chunk-preview",
    response_model=FileChunkPreviewResponse,
    summary="Parse + chunk PDF preview",
    description="Parse uploaded PDF with LlamaParse and preview section-aware chunks.",
)
async def chunk_pdf_preview(
    file: UploadFile = File(..., description="PDF file to parse and chunk"),
    chunk_size_chars: int = Form(1800, alias="chunkSizeChars"),
    chunk_overlap_chars: int = Form(250, alias="chunkOverlapChars"),
    _admin: Dict[str, Any] = Depends(require_admin),
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
        chunking_svc = get_chunking_service()

        pages = await parser_svc.parse_pdf_to_markdown(temp_file_path)
        chunks = chunking_svc.chunk_markdown_pages(
            pages,
            chunk_size_chars=chunk_size_chars,
            chunk_overlap_chars=chunk_overlap_chars,
        )

        return FileChunkPreviewResponse(
            filename=file.filename,
            page_count=len(pages),
            chunk_count=len(chunks),
            chunk_size_chars=chunk_size_chars,
            chunk_overlap_chars=chunk_overlap_chars,
            chunks=[
                FileChunkPreviewItem(
                    chunk_index=c.chunk_index,
                    page_index_start=c.page_index_start,
                    page_index_end=c.page_index_end,
                    section_path=c.section_path,
                    text=c.text,
                )
                for c in chunks
            ],
        )
    except ValidationException as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"Chunk preview failed: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
    finally:
        if temp_file_path and os.path.exists(temp_file_path):
            try:
                os.unlink(temp_file_path)
            except Exception as cleanup_error:
                logger.warning(f"Failed to cleanup chunk-preview temp file: {cleanup_error}")
