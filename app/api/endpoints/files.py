"""
File Management Endpoints - Handle file uploads and downloads.
Refactored to use FileService and StoreService with MongoDB + R2.
"""

from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form, Query
from fastapi.responses import StreamingResponse
from typing import Optional, List, Dict, Any
from datetime import datetime
import tempfile
import os
import logging
import json
from io import BytesIO

from app.models.schemas import (
    FileUploadResponse,
    FileDetailResponse,
    FileListResponse,
    BatchFileUploadResponse,
    BatchFileUploadResult,
    BulkDeleteResponse,
    SyncCheckResponse,
    SyncResponse,
)
from app.services.rag.file_service import get_file_service
from app.services.rag.utils.file_utils import convert_custom_metadata_to_snake, convert_custom_metadata_to_camel

from app.core.exceptions import (
    NotFoundException,
    StorageException,
    GeminiException,
    ConflictException,
    ValidationException,
)
from app.dependencies.auth import require_admin, require_auth
from app.services.rag.utils.store_utils import resolve_store
from app.models.enums import FileStatus

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/files", tags=["Files"])


@router.post(
    "",
    response_model=FileUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload file to store",
    description="Upload a document file to R2 and Gemini File Search for RAG.",
)
async def upload_file(
    file: UploadFile = File(..., description="File to upload"),
    display_name: Optional[str] = Form(None, alias="displayName", description="Display name for the file"),
    store_id: Optional[str] = Form(None, alias="storeId", description="Target store ID (uses default if not provided)"),
    custom_metadata: Optional[str] = Form(None, alias="customMetadata", description="JSON string of custom metadata"),
    enable_chunking: Optional[bool] = Form(None, alias="enableChunking", description="Enable custom chunking"),
    _admin: Dict[str, Any] = Depends(require_admin),
):
    """
    Upload a file to R2 storage and Gemini File Search (synchronous).

    Waits until both R2 and Gemini processing complete before returning.

    **Required metadata:**
    - `access_scope`: bắt buộc (e.g. `"admin"`, `"lecture"`, hoặc `"student"`)
    - `academic_year` hoặc `cohort`: ít nhất một trong hai

    **Custom Metadata example:**
    `'{"accessScope": "student", "academicYear": "2024-2025", "cohort": "K21"}'`
    """
    temp_file_path = None
    file_svc = get_file_service()
    
    try:
        from app.services.rag.utils.store_utils import resolve_store
        
        # Get store (from param or default store)
        resolved_store_id, store_name = await resolve_store(store_id)
        store_id = resolved_store_id
        
        # Parse custom metadata
        metadata_dict = {}
        if custom_metadata:
            try:
                metadata_dict = json.loads(custom_metadata)
                # Convert camelCase keys to snake_case for DB validation
                metadata_dict = convert_custom_metadata_to_snake(metadata_dict)
            except json.JSONDecodeError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid custom_metadata JSON format",
                )
        
        # Save uploaded file to temp location
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file.filename)[1], mode="wb") as temp_file:
            contents = await file.read()
            temp_file.write(contents)
            temp_file_path = temp_file.name
        
        # Upload file using FileService (validates metadata before upload)
        file_doc = await file_svc.upload_file(
            file_path=temp_file_path,
            original_filename=file.filename,
            store_id=store_id,
            store_name=store_name,
            display_name=display_name,
            custom_metadata=metadata_dict,
            enable_chunking=enable_chunking,
        )

        message = "File uploaded successfully"
        
        return FileUploadResponse(
            file_id=str(file_doc.id),
            store_id=file_doc.store_id,
            original_filename=file_doc.original_filename,
            display_name=file_doc.display_name,
            gemini_document_name=file_doc.gemini_document_name,
            file_size=file_doc.file_size,
            mime_type=file_doc.mime_type,
            status=file_doc.status.value if hasattr(file_doc.status, 'value') else str(file_doc.status),
            custom_metadata=convert_custom_metadata_to_camel(file_doc.custom_metadata or {}),
            created_at=file_doc.created_at.isoformat() if file_doc.created_at else datetime.now().isoformat(),
            message=message,
        )
        
    except ValidationException as e:
        logger.warning(f"Validation failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    
    except ConflictException as e:
        logger.warning(f"Duplicate file: {e}")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        )
    
    except (StorageException, GeminiException) as e:
        logger.error(f"File upload failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"File upload failed: {str(e)}",
        )
    
    except Exception as e:
        logger.error(f"Unexpected error during file upload: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error: {str(e)}",
        )
    
    finally:
        # Cleanup temp file
        if temp_file_path and os.path.exists(temp_file_path):
            try:
                os.unlink(temp_file_path)
            except Exception as e:
                logger.warning(f"Failed to delete temp file {temp_file_path}: {e}")


@router.get(
    "",
    response_model=FileListResponse,
    summary="List files",
    description="List files with optional filters and pagination.",
)
async def list_files(
    store_id: Optional[str] = Query(None, alias="storeId", description="Filter by store ID"),
    file_status: Optional[str] = Query(None, alias="fileStatus", description="Filter by status"),
    metadata_filter: Optional[str] = Query(None, alias="metadataFilter", description="JSON filter for metadata"),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(50, ge=1, le=100, description="Items per page"),
    _user: Dict[str, Any] = Depends(require_auth),
):
    """
    List files with pagination and filters.
    
    **Metadata Filter example:**
    `?metadataFilter={"academicYear":"2024-2025"}`
    """
        
    try:
        
        file_svc = get_file_service()
        
        # Parse status
        status_enum = None
        if file_status:
            try:
                status_enum = FileStatus(file_status.lower())
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid status: {file_status}",
                )
        
        # Parse metadata filter
        custom_metadata_filter = None
        if metadata_filter:
            try:
                custom_metadata_filter = json.loads(metadata_filter)
                # Convert camelCase keys to snake_case for DB query
                custom_metadata_filter = convert_custom_metadata_to_snake(custom_metadata_filter)
            except json.JSONDecodeError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid metadataFilter JSON format",
                )
        
        skip = (page - 1) * limit
        files, total = await file_svc.list_files(
            store_id=store_id,
            status=status_enum,
            custom_metadata_filter=custom_metadata_filter,
            user_role=_user.get("role", "student"),
            skip=skip,
            limit=limit,
        )

        return FileListResponse(
            files=[
                FileDetailResponse(
                    file_id=str(f.id),
                    store_id=f.store_id,
                    original_filename=f.original_filename,
                    display_name=f.display_name,
                    gemini_document_name=f.gemini_document_name,
                    file_size=f.file_size,
                    mime_type=f.mime_type,
                    storage_path=f.storage_path,
                    status=f.status.value if hasattr(f.status, "value") else str(f.status),
                    custom_metadata=convert_custom_metadata_to_camel(f.custom_metadata or {}),
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
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list files: {str(e)}",
        )


@router.get(
    "/check-sync",
    response_model=SyncCheckResponse,
    summary="Check file sync status",
    description="Compare files across MongoDB, R2, and Gemini to identify sync issues.",
)
async def check_sync(_admin: Dict[str, Any] = Depends(require_admin)):
    """
    Check synchronization status of files across all 3 storage systems.
    """
    try:
        file_svc = get_file_service()
        result = await file_svc.check_sync()
        return SyncCheckResponse(**result)
    except Exception as e:
        logger.error(f"Error during check-sync: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Check sync failed: {str(e)}",
        )


@router.post(
    "/batch",
    response_model=BatchFileUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Batch upload files",
    description="Upload multiple files at once, each with its own display name and metadata.",
)
async def batch_upload_files(
    files: List[UploadFile] = File(..., description="Files to upload"),
    store_id: Optional[str] = Form(None, alias="storeId", description="Target store ID (uses default if not provided)"),
    display_names: Optional[str] = Form(None, alias="displayNames", description="JSON array of display names (one per file, use null for auto)"),
    metadata_list: Optional[str] = Form(None, alias="metadataList", description="JSON array of metadata objects (one per file, use null or {} for no metadata)"),
    enable_chunking: Optional[bool] = Form(None, alias="enableChunking", description="Enable custom chunking for all files"),
    _admin: Dict[str, Any] = Depends(require_admin),
):
    """
    Batch upload multiple files to R2 storage and Gemini File Search.
    """
    file_svc = get_file_service()
    
    try:
        resolved_store_id, store_name = await resolve_store(store_id)
        store_id = resolved_store_id
        
        # Parse display_names
        names_list = []
        if display_names:
            try:
                names_list = json.loads(display_names)
                if not isinstance(names_list, list):
                    raise HTTPException(status_code=400, detail="display_names must be a list")
            except json.JSONDecodeError:
                raise HTTPException(status_code=400, detail="Invalid display_names JSON")
        
        # Parse metadata_list
        meta_list = []
        if metadata_list:
            try:
                meta_list = json.loads(metadata_list)
                if not isinstance(meta_list, list):
                    raise HTTPException(status_code=400, detail="metadata_list must be a list")
                # Convert each metadata object's keys to snake_case
                meta_list = [convert_custom_metadata_to_snake(m) if isinstance(m, dict) else m for m in meta_list]
            except json.JSONDecodeError:
                raise HTTPException(status_code=400, detail="Invalid metadata_list JSON")
        
        results = []
        successful = 0
        failed = 0
        
        # Save each file to temp location and upload
        for idx, file in enumerate(files):
            temp_file_path = None
            try:
                display_name = names_list[idx] if idx < len(names_list) and names_list[idx] is not None else None
                metadata_dict = meta_list[idx] if idx < len(meta_list) and isinstance(meta_list[idx], dict) else {}
                
                with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file.filename)[1], mode="wb") as temp_file:
                    contents = await file.read()
                    temp_file.write(contents)
                    temp_file_path = temp_file.name
                
                file_doc = await file_svc.upload_file(
                    file_path=temp_file_path,
                    original_filename=file.filename,
                    store_id=store_id,
                    store_name=store_name,
                    display_name=display_name,
                    custom_metadata=metadata_dict,
                    enable_chunking=enable_chunking,
                )
                
                results.append(BatchFileUploadResult(
                    original_filename=file.filename,
                    success=True,
                    file_id=str(file_doc.id),
                    display_name=file_doc.display_name,
                    gemini_document_name=file_doc.gemini_document_name,
                    message="Uploaded successfully",
                ))
                successful += 1
                
            except Exception as e:
                logger.error(f"Failed to upload file {file.filename}: {e}")
                results.append(BatchFileUploadResult(original_filename=file.filename, success=False, error=str(e)))
                failed += 1
            finally:
                if temp_file_path and os.path.exists(temp_file_path):
                    os.unlink(temp_file_path)
        
        return BatchFileUploadResponse(total=len(files), successful=successful, failed=failed, results=results)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Batch upload error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/sync",
    response_model=SyncResponse,
    summary="Sync files across storage systems",
)
async def sync_files(_admin: Dict[str, Any] = Depends(require_admin)):
    """
    Synchronize files across MongoDB, R2, and Gemini.
    """
    try:
        file_svc = get_file_service()
        result = await file_svc.sync_files()
        return SyncResponse(**result)
    except Exception as e:
        logger.error(f"Error during sync: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete(
    "/all",
    response_model=BulkDeleteResponse,
    summary="Delete all files in store",
)
async def delete_all_files_in_store(
    store_id: Optional[str] = Query(None, alias="storeId"),
    _admin: Dict[str, Any] = Depends(require_admin),
):
    """
    Delete all files in a store.
    """
    try:
        # Resolve store_id if not provided
        resolved_store_id, _ = await resolve_store(store_id)
        
        file_svc = get_file_service()
        deleted_count = await file_svc.delete_all_files_in_store(resolved_store_id)
        
        return BulkDeleteResponse(
            deleted_count=deleted_count,
            message=f"Deleted {deleted_count} files from store {resolved_store_id}",
        )
    except Exception as e:
        logger.error(f"Error deleting files: {e}", exc_info=True)
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
            store_id=file_doc.store_id,
            original_filename=file_doc.original_filename,
            display_name=file_doc.display_name,
            gemini_document_name=file_doc.gemini_document_name,
            file_size=file_doc.file_size,
            mime_type=file_doc.mime_type,
            storage_path=file_doc.storage_path,
            status=file_doc.status.value if hasattr(file_doc.status, "value") else str(file_doc.status),
            custom_metadata=convert_custom_metadata_to_camel(file_doc.custom_metadata or {}),
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
)
async def download_file(file_id: str, _user: Dict[str, Any] = Depends(require_auth)):
    try:
        file_svc = get_file_service()
        file_obj, filename, mime_type = await file_svc.download_file(file_id, user_role=_user.get("role", "student"))
        file_data = file_obj.read()
        return StreamingResponse(
            BytesIO(file_data),
            media_type=mime_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
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
        return None
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


