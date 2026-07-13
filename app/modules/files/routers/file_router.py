from __future__ import annotations

import logging
import urllib.parse
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import StreamingResponse

from app.core.auth import JWTPayload
from app.core.dependencies import from_form, require_admin, require_auth
from app.core.exceptions import AppException
from app.modules.files.dtos import (
    BatchFileUploadRequest,
    BatchFileUploadResponse,
    FileDetailResponse,
    FileListResponse,
    FileUploadRequest,
    FileUploadResponse,
    UpdateFileRequest,
)
from app.modules.files.services.file_api_service import get_file_api_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/files", tags=["Files"])


@router.post(
    "",
    response_model=FileUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload file",
    description="Upload a document file to R2.",
)
async def upload_file(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="File to upload"),
    req: FileUploadRequest = Depends(from_form(FileUploadRequest)),
    _admin: JWTPayload = Depends(require_admin),
):
    try:
        file_api_svc = get_file_api_service()
        outcome = await file_api_svc.upload_file(file=file, request=req)
        for task in outcome.background_tasks:
            background_tasks.add_task(file_api_svc.process_background_task, task)
        return outcome.response
    except AppException:
        raise
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Unexpected error during file upload: %s", exc, exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Internal server error: {str(exc)}") from exc


@router.get(
    "",
    response_model=FileListResponse,
    summary="List files",
    description="List files with optional filters and pagination.",
)
async def list_files(
    file_status: Optional[str] = Query(None, alias="fileStatus", description="Filter by status"),
    metadata_filter: Optional[str] = Query(None, alias="metadataFilter", description="JSON filter for metadata"),
    lecturer_only: Optional[bool] = Query(None, alias="lecturerOnly", description="Filter by lecturer-only visibility"),
    keywords: Optional[str] = Query(None, description="Search by display name"),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(50, ge=1, le=100, description="Items per page"),
    user: JWTPayload = Depends(require_auth),
):
    try:
        return await get_file_api_service().list_files(
            file_status=file_status,
            metadata_filter=metadata_filter,
            lecturer_only=lecturer_only,
            keywords=keywords,
            page=page,
            limit=limit,
            user=user,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Error listing files: %s", exc, exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to list files: {str(exc)}") from exc


@router.post(
    "/batch",
    response_model=BatchFileUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Batch upload files",
    description="Upload multiple files at once, each with its own display name and metadata.",
)
async def batch_upload_files(
    background_tasks: BackgroundTasks,
    request: Request,
    files: List[UploadFile] = File(..., description="Files to upload"),
    req: BatchFileUploadRequest = Depends(from_form(BatchFileUploadRequest)),
    _admin: JWTPayload = Depends(require_admin),
):
    try:
        file_api_svc = get_file_api_service()
        outcome = await file_api_svc.batch_upload_files(
            files=files,
            request=req,
            client_id=request.headers.get("X-Client-ID"),
        )
        for task in outcome.background_tasks:
            background_tasks.add_task(file_api_svc.process_background_task, task)
        return outcome.response
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Batch upload error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get(
    "/trash",
    response_model=FileListResponse,
    response_model_exclude_none=True,
    summary="List soft-deleted files",
)
async def list_deleted_files(
    file_status: Optional[str] = Query(None, alias="fileStatus"),
    metadata_filter: Optional[str] = Query(None, alias="metadataFilter"),
    lecturer_only: Optional[bool] = Query(None, alias="lecturerOnly"),
    keywords: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    admin: JWTPayload = Depends(require_admin),
):
    return await get_file_api_service().list_files(
        file_status=file_status,
        metadata_filter=metadata_filter,
        lecturer_only=lecturer_only,
        keywords=keywords,
        page=page,
        limit=limit,
        user=admin,
        deleted_only=True,
    )


@router.get(
    "/{file_id}",
    response_model=FileDetailResponse,
    summary="Get file details",
)
async def get_file(file_id: str, user: JWTPayload = Depends(require_auth)):
    try:
        return await get_file_api_service().get_file_detail(file_id, user)
    except HTTPException:
        raise
    except AppException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get(
    "/{file_id}/download",
    summary="Download file",
    description="Download the original uploaded file or its markdown version.",
)
async def download_file_endpoint(
    file_id: str,
    format: str = Query("original", description="Download format: original | markdown"),
    user: JWTPayload = Depends(require_auth),
):
    try:
        file_obj, filename, mime_type = await get_file_api_service().download_file(file_id, format, user)
        encoded_filename = urllib.parse.quote(filename)
        return StreamingResponse(
            file_obj,
            media_type=mime_type,
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}"},
        )
    except HTTPException:
        raise
    except AppException:
        raise
    except Exception as exc:
        logger.error("Error downloading file %s: %s", file_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.patch(
    "/{file_id}",
    response_model=FileDetailResponse,
    summary="Update file details (display name, metadata)",
)
async def update_file(
    file_id: str,
    request: UpdateFileRequest,
    _admin: JWTPayload = Depends(require_admin),
):
    try:
        return await get_file_api_service().update_file(file_id, request)
    except HTTPException:
        raise
    except AppException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.delete(
    "/{file_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete file",
)
async def delete_file(file_id: str, _admin: JWTPayload = Depends(require_admin)):
    try:
        await get_file_api_service().delete_file(file_id, _admin.user_id)
        return
    except AppException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post(
    "/{file_id}/restore",
    response_model=FileDetailResponse,
    response_model_exclude_none=True,
    summary="Restore a soft-deleted file",
)
async def restore_file(file_id: str, _admin: JWTPayload = Depends(require_admin)):
    try:
        return await get_file_api_service().restore_file(file_id)
    except AppException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.delete(
    "/{file_id}/purge",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Permanently purge a soft-deleted file",
)
async def purge_file(file_id: str, _admin: JWTPayload = Depends(require_admin)):
    try:
        await get_file_api_service().purge_file(file_id)
        return
    except AppException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
