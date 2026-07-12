from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.core.auth import JWTPayload
from app.core.dependencies import require_admin
from app.core.exceptions import AppException
from app.modules.files.dtos import FileParsePreviewResponse
from app.modules.files.services.file_debug_service import get_file_debug_service

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
    try:
        return await get_file_debug_service().parse_pdf_preview(file)
    except HTTPException:
        raise
    except AppException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
