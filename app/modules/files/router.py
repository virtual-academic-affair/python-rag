"""
File Management Endpoints - Handle file uploads and downloads.
Refactored to use FileService with MongoDB + R2, without Gemini.
"""

from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form, Query, BackgroundTasks, Request
from fastapi.responses import StreamingResponse
from typing import Optional, List, Dict, Any
from datetime import datetime
import tempfile
import os
import logging
import json
from io import BytesIO

from app.modules.files.schemas import (
    FileUploadResponse,
    FileDetailResponse,
    FileListResponse,
    BatchFileUploadResponse,
    BatchFileUploadResult,
    BulkDeleteResponse,
    UpdateFileRequest,
)
from app.modules.files.service import get_file_service
from app.modules.files.notifier import get_file_status_notifier
from app.integrations.llamaparse.client import get_llamaparse_client
from app.modules.rag.ingestion.chunking import get_chunking_service
from app.modules.rag.ingestion.service import get_ingestion_service
from app.core.converters import (
    convert_custom_metadata_to_snake,
    convert_custom_metadata_to_camel,
)
from app.modules.files.utils import (
    get_download_url,
)

from app.core.exceptions import (
    NotFoundException,
    StorageException,
    ConflictException,
    ValidationException,
)
from app.core.dependencies import require_admin, require_auth
from app.modules.files.models import FileStatus

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/files", tags=["Files"])


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
    display_name: Optional[str] = Form(None, alias="displayName", description="Display name for the file"),
    custom_metadata: Optional[str] = Form(None, alias="customMetadata", description="JSON string of custom metadata"),
    client_id: Optional[str] = Form(None, alias="clientId", description="WebSocket client id for upload progress events"),
    _admin: Dict[str, Any] = Depends(require_admin),
):
    """Upload sync-to-R2 then continue parse/vector steps in background."""

    temp_file_path = None
    file_svc = get_file_service()

    try:
        metadata_dict = {}
        if custom_metadata:
            try:
                metadata_dict = json.loads(custom_metadata)
                metadata_dict = convert_custom_metadata_to_snake(metadata_dict)
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
            if client_id:
                await notifier.notify(client_id, payload)

        file_doc, bg_payload = await file_svc.upload_file_quick(
            file_path=temp_file_path,
            original_filename=file.filename,
            display_name=display_name,
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
            custom_metadata=convert_custom_metadata_to_camel(file_doc.custom_metadata or {}),
            created_at=file_doc.created_at.isoformat() if file_doc.created_at else datetime.now().isoformat(),
            file_url=get_download_url(file_doc.storage_path),
            markdown_file_url=get_download_url(file_doc.markdown_storage_path),
            message="File uploaded to storage. Background processing started.",
        )

    except ValidationException as e:
        logger.warning(f"Validation failed: {e}")
        if temp_file_path and os.path.exists(temp_file_path):
            os.unlink(temp_file_path)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    except ConflictException as e:
        logger.warning(f"Duplicate file: {e}")
        if temp_file_path and os.path.exists(temp_file_path):
            os.unlink(temp_file_path)
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))

    except StorageException as e:
        logger.error(f"File upload failed: {e}", exc_info=True)
        if temp_file_path and os.path.exists(temp_file_path):
            os.unlink(temp_file_path)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"File upload failed: {str(e)}")

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
    _user: Dict[str, Any] = Depends(require_auth),
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
                custom_metadata_filter = convert_custom_metadata_to_snake(custom_metadata_filter)

                from app.modules.metadata.service import get_metadata_service
                metadata_svc = get_metadata_service()
                is_valid, errors = await metadata_svc.validate_metadata(custom_metadata_filter)
                if not is_valid:
                    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid metadataFilter: {', '.join(errors)}")
            except json.JSONDecodeError:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid metadataFilter JSON format")

        skip = (page - 1) * limit
        files, total = await file_svc.list_files(
            status=status_enum,
            custom_metadata_filter=custom_metadata_filter,
            keywords=keywords,
            user_role=_user.get("role", "student"),
            skip=skip,
            limit=limit,
        )

        return FileListResponse(
            files=[
                FileDetailResponse(
                    file_id=str(f.id),
                    original_filename=f.original_filename,
                    display_name=f.display_name,
                    file_size=f.file_size,
                    mime_type=f.mime_type,
                    storage_path=f.storage_path,
                    status=f.status.value if hasattr(f.status, "value") else str(f.status),
                    custom_metadata=convert_custom_metadata_to_camel(f.custom_metadata or {}),
                    file_url=get_download_url(f.storage_path),
                    markdown_file_url=get_download_url(f.markdown_storage_path),
                    created_at=f.created_at.isoformat() if f.created_at else "",
                    updated_at=f.updated_at.isoformat() if f.updated_at else "",
                )
                for f in files
            ],
            total=total,
            page=page,
            limit=limit,
        )

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
    display_names: Optional[str] = Form(None, alias="displayNames", description="JSON array of display names (one per file, use null for auto)"),
    metadata_list: Optional[str] = Form(None, alias="metadataList", description="JSON array of metadata objects (one per file, use null or {} for no metadata)"),
    _admin: Dict[str, Any] = Depends(require_admin),
):
    """
    Batch upload multiple files to R2 storage and queue background processing.
    """
    file_svc = get_file_service()

    try:
        names_list = []
        if display_names:
            try:
                names_list = json.loads(display_names)
                if not isinstance(names_list, list):
                    raise HTTPException(status_code=400, detail="display_names must be a list")
            except json.JSONDecodeError:
                raise HTTPException(status_code=400, detail="Invalid display_names JSON")

        meta_list = []
        if metadata_list:
            try:
                meta_list = json.loads(metadata_list)
                if not isinstance(meta_list, list):
                    raise HTTPException(status_code=400, detail="metadata_list must be a list")
                meta_list = [convert_custom_metadata_to_snake(m) if isinstance(m, dict) else m for m in meta_list]
            except json.JSONDecodeError:
                raise HTTPException(status_code=400, detail="Invalid metadata_list JSON")

        results = []
        successful = 0
        failed = 0

        for idx, file in enumerate(files):
            temp_file_path = None
            try:
                display_name = names_list[idx] if idx < len(names_list) and names_list[idx] is not None else None
                metadata_dict = meta_list[idx] if idx < len(meta_list) and isinstance(meta_list[idx], dict) else {}

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
                # If error happens before process_file_background is scheduled, we need to clean up
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
async def get_file(file_id: str, _user: Dict[str, Any] = Depends(require_auth)):
    try:
        file_svc = get_file_service()
        file_doc = await file_svc.get_file_by_id(file_id, user_role=_user.get("role", "student"))
        if not file_doc:
            raise HTTPException(status_code=404, detail="File not found")

        return FileDetailResponse(
            file_id=str(file_doc.id),
            original_filename=file_doc.original_filename,
            display_name=file_doc.display_name,
            file_size=file_doc.file_size,
            mime_type=file_doc.mime_type,
            storage_path=file_doc.storage_path,
            status=file_doc.status.value if hasattr(file_doc.status, "value") else str(file_doc.status),
            custom_metadata=convert_custom_metadata_to_camel(file_doc.custom_metadata or {}),
            file_url=get_download_url(file_doc.storage_path),
            markdown_file_url=get_download_url(file_doc.markdown_storage_path),
            created_at=file_doc.created_at.isoformat() if file_doc.created_at else "",
            updated_at=file_doc.updated_at.isoformat() if file_doc.updated_at else "",
        )
    except HTTPException:
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
    _user: Dict[str, Any] = Depends(require_auth)
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
            user_role=_user.get("role", "student"),
            file_format=requested_format,
        )
        file_data = file_obj.read()
        return StreamingResponse(
            BytesIO(file_data),
            media_type=mime_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'}
        )
    except NotFoundException as e:
        raise HTTPException(status_code=404, detail=str(e))
    except HTTPException:
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
    _admin: Dict[str, Any] = Depends(require_admin)
):
    try:
        file_svc = get_file_service()
        file_doc = await file_svc.update_file(
            file_id=file_id, 
            display_name=request.display_name,
            custom_metadata=request.custom_metadata
        )
        if not file_doc:
            raise HTTPException(status_code=404, detail="File not found")

        return FileDetailResponse(
            file_id=str(file_doc.id),
            original_filename=file_doc.original_filename,
            display_name=file_doc.display_name,
            file_size=file_doc.file_size,
            mime_type=file_doc.mime_type,
            storage_path=file_doc.storage_path,
            status=file_doc.status.value if hasattr(file_doc.status, "value") else str(file_doc.status),
            custom_metadata=convert_custom_metadata_to_camel(file_doc.custom_metadata or {}),
            file_url=get_download_url(file_doc.storage_path),
            markdown_file_url=get_download_url(file_doc.markdown_storage_path),
            created_at=file_doc.created_at.isoformat() if file_doc.created_at else "",
            updated_at=file_doc.updated_at.isoformat() if file_doc.updated_at else "",
        )
    except ValidationException as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.delete(
    "/{file_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete file",
)
async def delete_file(file_id: str, _admin: Dict[str, Any] = Depends(require_admin)):
    try:
        file_svc = get_file_service()
        await file_svc.delete_file(file_id)
        return
    except NotFoundException as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

