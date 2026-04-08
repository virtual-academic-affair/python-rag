"""
File Management Endpoints - Handle file uploads and downloads.
Refactored to use FileService and StoreService with MongoDB + R2.
"""

from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form, Query, BackgroundTasks
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
    UpdateFileRequest,
    FileParsePreviewResponse,
    FileParsePreviewPage,
    FileChunkPreviewResponse,
    FileChunkPreviewItem,
    FileIngestChunksResponse,
)
from app.services.rag.file_service import get_file_service
from app.services.rag.llamaparse_ingest_service import get_llamaparse_ingest_service
from app.services.rag.chunking_service import get_chunking_service
from app.services.rag.rag_ingest_service import get_rag_ingest_service
from app.services.rag.file_status_notifier import get_file_status_notifier
from app.services.rag.utils.file_utils import (
    convert_custom_metadata_to_snake,
    convert_custom_metadata_to_camel,
    get_download_url,
)

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
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="File to upload"),
    display_name: Optional[str] = Form(None, alias="displayName", description="Display name for the file"),
    store_id: Optional[str] = Form(None, alias="storeId", description="Target store ID (uses default if not provided)"),
    custom_metadata: Optional[str] = Form(None, alias="customMetadata", description="JSON string of custom metadata"),
    client_id: Optional[str] = Form(None, alias="clientId", description="WebSocket client id for upload progress events"),
    _admin: Dict[str, Any] = Depends(require_admin),
):
    """Upload sync-to-R2 then continue parse/vector steps in background."""
    notifier = get_file_status_notifier()

    async def _progress_callback(payload: Dict[str, Any]):
        if client_id:
            await notifier.notify(client_id, payload)

    async def _background_process(file_id: str, bg_file_path: str, bg_display_name: str, bg_metadata: Dict[str, Any]):
        await file_svc.process_file_background(
            file_id=file_id,
            file_path=bg_file_path,
            display_name=bg_display_name,
            custom_metadata=bg_metadata,
            progress_callback=_progress_callback,
        )

    temp_file_path = None
    file_svc = get_file_service()

    try:
        # Get store (from param or default store)
        resolved_store_id, store_name = await resolve_store(store_id)
        store_id = resolved_store_id

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

        file_doc, bg_payload = await file_svc.upload_file_quick(
            file_path=temp_file_path,
            original_filename=file.filename,
            store_id=store_id,
            store_name=store_name,
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
        )

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
            file_url=get_download_url(file_doc.storage_path),
            markdown_file_url=get_download_url(file_doc.markdown_storage_path),
            summary=file_doc.summary,
            table_of_contents=file_doc.table_of_contents or [],
            message="File uploaded to storage. Background processing started.",
        )

    except ValidationException as e:
        logger.warning(f"Validation failed: {e}")
        if temp_file_path and os.path.exists(temp_file_path):
            os.unlink(temp_file_path)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    except ConflictException as e:
        logger.warning(f"Duplicate file: {e}")
        if temp_file_path and os.path.exists(temp_file_path):
            os.unlink(temp_file_path)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        )

    except (StorageException, GeminiException) as e:
        logger.error(f"File upload failed: {e}", exc_info=True)
        if temp_file_path and os.path.exists(temp_file_path):
            os.unlink(temp_file_path)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"File upload failed: {str(e)}",
        )

    except Exception as e:
        logger.error(f"Unexpected error during file upload: {e}", exc_info=True)
        if temp_file_path and os.path.exists(temp_file_path):
            os.unlink(temp_file_path)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error: {str(e)}",
        )


@router.post(
    "/parse-preview",
    response_model=FileParsePreviewResponse,
    summary="Parse PDF to markdown preview (Sprint 1)",
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

        parser_svc = get_llamaparse_ingest_service()
        pages = await parser_svc.parse_pdf_to_markdown(temp_file_path)

        return FileParsePreviewResponse(
            filename=file.filename,
            page_count=len(pages),
            pages=[
                FileParsePreviewPage(page_index=p.page_index, markdown=p.markdown)
                for p in pages
            ],
        )
    except ValidationException as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except HTTPException:
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


@router.post(
    "/chunk-preview",
    response_model=FileChunkPreviewResponse,
    summary="Parse + chunk PDF preview (Sprint 2)",
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

        parser_svc = get_llamaparse_ingest_service()
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
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Chunk preview failed: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
    finally:
        if temp_file_path and os.path.exists(temp_file_path):
            try:
                os.unlink(temp_file_path)
            except Exception as cleanup_error:
                logger.warning(f"Failed to cleanup chunk-preview temp file: {cleanup_error}")


@router.post(
    "/{file_id}/ingest-chunks",
    response_model=FileIngestChunksResponse,
    summary="Ingest file chunks (Sprint 3)",
    description="Parse file from R2 storage, chunk content, and persist to Mongo.",
)
async def ingest_file_chunks(
    file_id: str,
    chunk_size_chars: int = Form(1800, alias="chunkSizeChars"),
    chunk_overlap_chars: int = Form(250, alias="chunkOverlapChars"),
    _admin: Dict[str, Any] = Depends(require_admin),
):
    temp_file_path = None
    try:
        file_svc = get_file_service()
        file_doc = await file_svc.get_file(file_id)

        if not file_doc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")

        # Download to temp before parse
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
        temp_file_path = temp_file.name
        temp_file.close()

        await file_svc.download_file(file_id=file_id, output_path=temp_file_path)

        ingest_svc = get_rag_ingest_service()
        result = await ingest_svc.ingest_pdf_chunks(
            file_id=file_id,
            file_name=file_doc.display_name,
            file_path=temp_file_path,
            metadata=file_doc.custom_metadata,
            chunk_size_chars=chunk_size_chars,
            chunk_overlap_chars=chunk_overlap_chars,
        )

        return FileIngestChunksResponse(
            file_id=result["file_id"],
            file_name=file_doc.display_name,
            page_count=result["page_count"],
            chunk_count=result["chunk_count"],
            inserted_count=result["inserted_count"],
            deleted_previous_mongo=result["deleted_previous_mongo"],
        )
    except ValidationException as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Ingest chunks failed for file {file_id}: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
    finally:
        if temp_file_path and os.path.exists(temp_file_path):
            try:
                os.unlink(temp_file_path)
            except Exception as cleanup_error:
                logger.warning(f"Failed to cleanup ingest temp file: {cleanup_error}")

@router.get(
    "",
    response_model=FileListResponse,
    summary="List files",
    description="List files in the default store with optional filters and pagination.",
)
async def list_files(
    file_status: Optional[str] = Query(None, alias="fileStatus", description="Filter by status"),
    metadata_filter: Optional[str] = Query(None, alias="metadataFilter", description="JSON filter for metadata"),
    keywords: Optional[str] = Query(None, description="Search by display name"),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(50, ge=1, le=100, description="Items per page"),
    _user: Dict[str, Any] = Depends(require_auth),
):
    """
    List files in the default store with pagination and filters.

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

                # Validate metadata filter (allow arrays)
                from app.services.rag.metadata_service import get_metadata_service
                metadata_svc = get_metadata_service()
                is_valid, errors = await metadata_svc.validate_metadata(custom_metadata_filter)
                if not is_valid:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Invalid metadataFilter: {', '.join(errors)}",
                    )
            except json.JSONDecodeError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid metadataFilter JSON format",
                )


        resolved_store_id, _ = await resolve_store(None)

        skip = (page - 1) * limit
        files, total = await file_svc.list_files(
            store_id=resolved_store_id,
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
                    store_id=f.store_id,
                    original_filename=f.original_filename,
                    display_name=f.display_name,
                    gemini_document_name=f.gemini_document_name,
                    file_size=f.file_size,
                    mime_type=f.mime_type,
                    storage_path=f.storage_path,
                    status=f.status.value if hasattr(f.status, "value") else str(f.status),
                    custom_metadata=convert_custom_metadata_to_camel(f.custom_metadata or {}),
                    file_url=get_download_url(f.storage_path),
                    markdown_file_url=get_download_url(f.markdown_storage_path),
                    summary=f.summary,
                    table_of_contents=f.table_of_contents or [],
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
    "/admin",
    response_model=FileListResponse,
    summary="List files (Admin)",
    description="Admin file listing across all stores or filtered by storeId.",
)
async def list_files_admin(
    store_id: Optional[str] = Query(None, alias="storeId", description="Filter by store ID. If empty, lists across all stores."),
    file_status: Optional[str] = Query(None, alias="fileStatus", description="Filter by status"),
    metadata_filter: Optional[str] = Query(None, alias="metadataFilter", description="JSON filter for metadata"),
    keywords: Optional[str] = Query(None, description="Search by display name"),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(50, ge=1, le=100, description="Items per page"),
    _admin: Dict[str, Any] = Depends(require_admin),
):
    """
    Admin endpoint to list files with pagination and filters.
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
                custom_metadata_filter = convert_custom_metadata_to_snake(custom_metadata_filter)

                # Validate metadata filter (allow arrays)
                from app.services.rag.metadata_service import get_metadata_service
                metadata_svc = get_metadata_service()
                is_valid, errors = await metadata_svc.validate_metadata(custom_metadata_filter)
                if not is_valid:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Invalid metadataFilter: {', '.join(errors)}",
                    )
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
            keywords=keywords,
            user_role="admin",
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
                    file_url=get_download_url(f.storage_path),
                    markdown_file_url=get_download_url(f.markdown_storage_path),
                    summary=f.summary,
                    table_of_contents=f.table_of_contents or [],
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
        logger.error(f"Error listing files (admin): {e}", exc_info=True)
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
                )

                results.append(BatchFileUploadResult(
                    original_filename=file.filename,
                    success=True,
                    file_id=str(file_doc.id),
                    display_name=file_doc.display_name,
                    gemini_document_name=file_doc.gemini_document_name,
                    file_url=get_download_url(file_doc.storage_path),
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
            file_url=get_download_url(file_doc.storage_path),
            markdown_file_url=get_download_url(file_doc.markdown_storage_path),
            summary=file_doc.summary,
            table_of_contents=file_doc.table_of_contents or [],
            created_at=file_doc.created_at.isoformat() if file_doc.created_at else "",
            updated_at=file_doc.updated_at.isoformat() if file_doc.updated_at else "",
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.patch(
    "/{file_id}",
    response_model=FileDetailResponse,
    summary="Update file display name",
)
async def update_file(
    file_id: str,
    request: UpdateFileRequest,
    _admin: Dict[str, Any] = Depends(require_admin)
):
    try:
        file_svc = get_file_service()
        file_doc = await file_svc.update_file_display_name(file_id, request.display_name)
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
            file_url=get_download_url(file_doc.storage_path),
            markdown_file_url=get_download_url(file_doc.markdown_storage_path),
            summary=file_doc.summary,
            table_of_contents=file_doc.table_of_contents or [],
            created_at=file_doc.created_at.isoformat() if file_doc.created_at else "",
            updated_at=file_doc.updated_at.isoformat() if file_doc.updated_at else "",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating file: {e}", exc_info=True)
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


