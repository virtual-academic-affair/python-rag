from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form, Query, BackgroundTasks, Request
from fastapi.responses import StreamingResponse
from typing import Optional, List, Dict, Any
from datetime import datetime
import tempfile
import os
import logging
import json
import urllib.parse
from io import BytesIO

from app.modules.files.dtos import (
    FileUploadResponse,
    FileDetailResponse,
    FileListResponse,
    BatchFileUploadResponse,
    BatchFileUploadResult,
    UpdateFileRequest,
    FileUploadRequest,
    BatchFileUploadRequest
)
from app.modules.metadata.dtos import FileMetadataResponse
from app.modules.files.services.file_service import get_file_service
from app.modules.metadata.services.metadata_service import get_metadata_service
from app.modules.files.utils.notifier import get_file_status_notifier
from app.modules.files.utils.file_helpers import get_download_url
from app.core.auth import JWTPayload
from app.core.exceptions import AppException, NotFoundException
from app.core.dependencies import require_admin, require_auth, from_form
from app.modules.files.models.file import FileStatus

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/files", tags=["Files"])


def _to_file_detail_response(file_doc) -> FileDetailResponse:
    return FileDetailResponse(
        file_id=str(file_doc.id),
        original_filename=file_doc.original_filename,
        display_name=file_doc.display_name,
        file_size=file_doc.file_size,
        mime_type=file_doc.mime_type,
        storage_path=file_doc.storage_path,
        status=file_doc.status.value if hasattr(file_doc.status, "value") else str(file_doc.status),
        custom_metadata=FileMetadataResponse.from_model(file_doc.custom_metadata) if file_doc.custom_metadata else None,
        file_url=get_download_url(file_doc.storage_path),
        markdown_file_url=get_download_url(file_doc.markdown_storage_path) if file_doc.markdown_storage_path else None,
        table_of_contents=file_doc.table_of_contents,
        created_at=file_doc.created_at.isoformat() if file_doc.created_at else "",
        updated_at=file_doc.updated_at.isoformat() if file_doc.updated_at else "",
    )

async def _background_process(file_id: str, bg_file_path: str, bg_display_name: str, bg_metadata: Dict[str, Any], progress_cb=None):
    file_svc = get_file_service()
    await file_svc.process_file_background(
        file_id=file_id,
        file_path=bg_file_path,
        display_name=bg_display_name,
        custom_metadata=bg_metadata,
        progress_callback=progress_cb
    )

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
    """Upload sync-to-R2 then continue parse/vector steps in background."""
    temp_file_path = None
    file_svc = get_file_service()

    try:
        metadata_dict = {}
        if req.custom_metadata:
            try:
                metadata_dict = json.loads(req.custom_metadata)
            except json.JSONDecodeError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid custom_metadata JSON format",
                )

        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file.filename)[1], mode="wb") as temp_file:
            contents = await file.read()
            temp_file.write(contents)
            temp_file_path = temp_file.name

        notifier = get_file_status_notifier()
        async def _progress_callback(payload: Dict[str, Any]):
            if req.client_id:
                await notifier.notify(req.client_id, payload)

        file_doc, bg_payload = await file_svc.upload_file_quick(
            file_path=temp_file_path,
            original_filename=file.filename,
            display_name=req.display_name,
            custom_metadata=metadata_dict,
            progress_callback=_progress_callback,
        )

        background_tasks.add_task(
            _background_process,
            bg_payload["file_id"],
            temp_file_path,
            bg_payload["display_name"],
            bg_payload["custom_metadata"],
            _progress_callback
        )

        return FileUploadResponse(
            file_id=str(file_doc.id),
            original_filename=file_doc.original_filename,
            display_name=file_doc.display_name,
            file_size=file_doc.file_size,
            mime_type=file_doc.mime_type,
            status=file_doc.status.value if hasattr(file_doc.status, 'value') else str(file_doc.status),
            custom_metadata=FileMetadataResponse.from_model(file_doc.custom_metadata) if file_doc.custom_metadata else None,
            created_at=file_doc.created_at.isoformat() if file_doc.created_at else datetime.now().isoformat(),
            file_url=get_download_url(file_doc.storage_path),
            markdown_file_url=get_download_url(file_doc.markdown_storage_path) if file_doc.markdown_storage_path else None,
            message="File uploaded to storage. Background processing started.",
        )

    except AppException:
        if temp_file_path and os.path.exists(temp_file_path):
            os.unlink(temp_file_path)
        raise

    except Exception as e:
        logger.error(f"Unexpected error during file upload: {e}", exc_info=True)
        if temp_file_path and os.path.exists(temp_file_path):
            os.unlink(temp_file_path)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Internal server error: {str(e)}")

@router.get(
    "",
    response_model=FileListResponse,
    summary="List files",
    description="List files with optional filters and pagination.",
)
async def list_files(
    file_status: Optional[str] = Query(None, alias="fileStatus", description="Filter by status"),
    metadata_filter: Optional[str] = Query(None, alias="metadataFilter", description="JSON filter for metadata"),
    keywords: Optional[str] = Query(None, description="Search by display name"),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(50, ge=1, le=100, description="Items per page"),
    _user: JWTPayload = Depends(require_auth),
):
    try:
        file_svc = get_file_service()

        status_enum = None
        if file_status:
            try:
                status_enum = FileStatus(file_status.lower())
            except ValueError:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid status: {file_status}")

        custom_metadata_filter = None
        if metadata_filter:
            try:
                custom_metadata_filter = json.loads(metadata_filter)
                metadata_svc = get_metadata_service()
                is_valid, errors = metadata_svc.validate_unified_filter(custom_metadata_filter)
                if not is_valid:
                    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid metadataFilter: {', '.join(errors)}")
            except json.JSONDecodeError:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid metadataFilter JSON format")

        skip = (page - 1) * limit
        files, total = await file_svc.list_files(
            status=status_enum,
            custom_metadata_filter=custom_metadata_filter,
            keywords=keywords,
            skip=skip,
            limit=limit,
        )

        return FileListResponse(
            files=[_to_file_detail_response(f) for f in files],
            total=total,
            page=page,
            limit=limit,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing files: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to list files: {str(e)}")

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
    """Batch upload multiple files to R2 storage and queue background processing."""
    file_svc = get_file_service()

    try:
        names_list = []
        if req.display_names:
            try:
                names_list = json.loads(req.display_names)
                if not isinstance(names_list, list):
                    raise HTTPException(status_code=400, detail="display_names must be a list")
            except json.JSONDecodeError:
                raise HTTPException(status_code=400, detail="Invalid display_names JSON")

        meta_list = []
        if req.metadata_list:
            try:
                meta_list = json.loads(req.metadata_list)
                if not isinstance(meta_list, list):
                    raise HTTPException(status_code=400, detail="metadata_list must be a list")
            except json.JSONDecodeError:
                raise HTTPException(status_code=400, detail="Invalid metadata_list JSON")

        results = []
        successful = 0
        failed = 0

        for idx, file in enumerate(files):
            temp_file_path = None
            try:
                display_name = names_list[idx] if idx < len(names_list) and names_list[idx] is not None else None
                metadata_dict = {}
                if idx < len(meta_list) and meta_list[idx] is not None:
                    if not isinstance(meta_list[idx], dict):
                        raise ValueError(f"Metadata at index {idx} must be a JSON object (dict)")
                    metadata_dict = meta_list[idx]

                with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file.filename)[1], mode="wb") as temp_file:
                    contents = await file.read()
                    temp_file.write(contents)
                    temp_file_path = temp_file.name

                client_id = request.headers.get("X-Client-ID")
                notifier = get_file_status_notifier()
                
                async def _progress_callback_bound(payload: Dict[str, Any], cid=client_id):
                    if cid:
                        await notifier.notify(cid, payload)

                file_doc, bg_payload = await file_svc.upload_file_quick(
                    file_path=temp_file_path,
                    original_filename=file.filename,
                    display_name=display_name,
                    custom_metadata=metadata_dict,
                    progress_callback=_progress_callback_bound,
                )

                background_tasks.add_task(
                    _background_process,
                    bg_payload["file_id"],
                    temp_file_path,
                    bg_payload["display_name"],
                    bg_payload["custom_metadata"],
                    _progress_callback_bound
                )

                results.append(BatchFileUploadResult(
                    original_filename=file.filename,
                    success=True,
                    file_id=str(file_doc.id),
                    display_name=file_doc.display_name,
                    file_url=get_download_url(file_doc.storage_path),
                    message="Uploaded successfully, background processing started.",
                ))
                successful += 1

            except Exception as e:
                logger.error(f"Failed to upload file {file.filename}: {e}")
                results.append(BatchFileUploadResult(original_filename=file.filename, success=False, error=str(e)))
                failed += 1
                if temp_file_path and os.path.exists(temp_file_path):
                    try:
                        os.unlink(temp_file_path)
                    except Exception as unlink_err:
                        logger.warning(f"Failed to clean up temp file on error: {unlink_err}")

        return BatchFileUploadResponse(total=len(files), successful=successful, failed=failed, results=results)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Batch upload error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.get(
    "/{file_id}",
    response_model=FileDetailResponse,
    summary="Get file details",
)
async def get_file(file_id: str, _user: JWTPayload = Depends(require_auth)):
    try:
        file_svc = get_file_service()
        file_doc = await file_svc.get_file_by_id(file_id)
        if not file_doc:
            raise NotFoundException("File", file_id)

        return _to_file_detail_response(file_doc)
    except HTTPException:
        raise
    except AppException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get(
    "/{file_id}/download",
    summary="Download file",
    description="Download the original uploaded file or its markdown version.",
)
async def download_file_endpoint(
    file_id: str, 
    format: str = Query("original", description="Download format: original | markdown"),
    _user: JWTPayload = Depends(require_auth)
):
    try:
        allowed_formats = {"original", "markdown"}
        requested_format = format.lower()
        if requested_format not in allowed_formats:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid format. Allowed values: original, markdown",
            )

        file_svc = get_file_service()
        file_obj, filename, mime_type = await file_svc.download_file(
            file_id,
            file_format=requested_format,
        )
        encoded_filename = urllib.parse.quote(filename)
        return StreamingResponse(
            file_obj,
            media_type=mime_type,
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}"}
        )
    except HTTPException:
        raise
    except AppException:
        raise
    except Exception as e:
        logger.error(f"Error downloading file {file_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.patch(
    "/{file_id}",
    response_model=FileDetailResponse,
    summary="Update file details (display name, metadata)",
)
async def update_file(
    file_id: str,
    request: UpdateFileRequest,
    _admin: JWTPayload = Depends(require_admin)
):
    try:
        file_svc = get_file_service()
        file_doc = await file_svc.update_file(
            file_id=file_id, 
            display_name=request.display_name,
            custom_metadata=(
                request.custom_metadata.model_dump(exclude_unset=True, by_alias=False)
                if request.custom_metadata
                else None
            )
        )
        if not file_doc:
            raise NotFoundException("File", file_id)

        return _to_file_detail_response(file_doc)
    except HTTPException:
        raise
    except AppException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.delete(
    "/{file_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete file",
)
async def delete_file(file_id: str, _admin: JWTPayload = Depends(require_admin)):
    try:
        file_svc = get_file_service()
        await file_svc.delete_file(file_id)
        return
    except AppException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
