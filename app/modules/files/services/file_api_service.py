"""HTTP-facing file workflow orchestration.

This service keeps file router thin while preserving API behavior.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import logging
import os
import tempfile
from typing import Any, Awaitable, Callable, Optional

from fastapi import HTTPException, UploadFile, status

from app.modules.files.dtos import (
    BatchFileUploadRequest,
    BatchFileUploadResponse,
    BatchFileUploadResult,
    FileDetailResponse,
    FileListItemResponse,
    FileListResponse,
    FileUploadRequest,
    FileUploadResponse,
    UpdateFileRequest,
)
from app.modules.files.models.file import FileStatus
from app.modules.files.services.file_service import FileService, get_file_service
from app.modules.files.utils.file_helpers import get_download_url
from app.modules.files.utils.notifier import get_file_status_notifier
from app.modules.metadata.dtos import FileMetadataResponse
from app.modules.metadata.services.metadata_service import get_metadata_service
from app.core.auth import JWTPayload
from app.core.exceptions import NotFoundException

logger = logging.getLogger(__name__)


@dataclass
class FileBackgroundTask:
    file_id: str
    file_path: str
    display_name: str
    custom_metadata: dict[str, Any]
    progress_callback: Callable[[dict[str, Any]], Awaitable[None]] | None = None


@dataclass
class FileUploadOutcome:
    response: FileUploadResponse
    background_tasks: list[FileBackgroundTask]


@dataclass
class BatchUploadOutcome:
    response: BatchFileUploadResponse
    background_tasks: list[FileBackgroundTask]


class FileApiService:
    def __init__(self, file_service: FileService | None = None):
        self._file_service = file_service or get_file_service()

    async def upload_file(self, *, file: UploadFile, request: FileUploadRequest) -> FileUploadOutcome:
        temp_file_path = None
        try:
            metadata_dict = self._parse_json_object(
                request.custom_metadata,
                field_name="custom_metadata",
            )
            temp_file_path = await self._write_temp_upload(file)
            progress_callback = self._build_progress_callback(request.client_id)

            file_doc, bg_payload = await self._file_service.upload_file_quick(
                file_path=temp_file_path,
                original_filename=file.filename,
                display_name=request.display_name,
                custom_metadata=metadata_dict,
                lecturer_only=request.lecturer_only,
                progress_callback=progress_callback,
            )

            response = FileUploadResponse(
                file_id=str(file_doc.id),
                original_filename=file_doc.original_filename,
                display_name=file_doc.display_name,
                file_size=file_doc.file_size,
                mime_type=file_doc.mime_type,
                status=file_doc.status.value if hasattr(file_doc.status, "value") else str(file_doc.status),
                custom_metadata=(
                    FileMetadataResponse.from_model(file_doc.custom_metadata)
                    if file_doc.custom_metadata
                    else None
                ),
                created_at=file_doc.created_at.isoformat() if file_doc.created_at else datetime.now().isoformat(),
                file_url=get_download_url(file_doc.storage_path),
                markdown_file_url=get_download_url(file_doc.markdown_storage_path) if file_doc.markdown_storage_path else None,
                message="File uploaded to storage. Background processing started.",
            )
            return FileUploadOutcome(
                response=response,
                background_tasks=[
                    FileBackgroundTask(
                        file_id=bg_payload["file_id"],
                        file_path=temp_file_path,
                        display_name=bg_payload["display_name"],
                        custom_metadata=bg_payload["custom_metadata"],
                        progress_callback=progress_callback,
                    )
                ],
            )
        except Exception:
            if temp_file_path and os.path.exists(temp_file_path):
                os.unlink(temp_file_path)
            raise

    async def list_files(
        self,
        *,
        file_status: Optional[str],
        metadata_filter: Optional[str],
        keywords: Optional[str],
        page: int,
        limit: int,
        user: JWTPayload,
        deleted_only: bool = False,
        lecturer_only: Optional[bool] = None,
    ) -> FileListResponse:
        status_enum = None
        if file_status:
            try:
                status_enum = FileStatus(file_status.lower())
            except ValueError as exc:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid status: {file_status}") from exc

        if deleted_only and user.role != "admin":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only admins can list deleted files")
        if not deleted_only and user.role != "admin":
            status_enum = FileStatus.READY

        custom_metadata_filter = None
        if metadata_filter:
            custom_metadata_filter = self._parse_json_object(
                metadata_filter,
                field_name="metadataFilter",
            )
            metadata_svc = get_metadata_service()
            is_valid, errors = metadata_svc.validate_unified_filter(custom_metadata_filter)
            if not is_valid:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid metadataFilter: {', '.join(errors)}")

        role_filter = self._build_role_filter(user)
        if lecturer_only is not None and user.role in ("admin", "lecture"):
            role_filter = {**(role_filter or {}), "lecturer_only": lecturer_only}
        skip = (page - 1) * limit
        files, total = await self._file_service.list_files(
            status=status_enum,
            custom_metadata_filter=custom_metadata_filter,
            keywords=keywords,
            role_filter=role_filter,
            deleted_only=deleted_only,
            skip=skip,
            limit=limit,
        )
        return FileListResponse(
            files=[self.to_file_list_item_response(file_doc) for file_doc in files],
            total=total,
            page=page,
            limit=limit,
        )

    async def batch_upload_files(
        self,
        *,
        files: list[UploadFile],
        request: BatchFileUploadRequest,
        client_id: str | None = None,
    ) -> BatchUploadOutcome:
        names_list = self._parse_json_list(request.display_names, field_name="display_names")
        meta_list = self._parse_json_list(request.metadata_list, field_name="metadata_list")

        results: list[BatchFileUploadResult] = []
        background_tasks: list[FileBackgroundTask] = []
        successful = failed = 0

        for idx, file in enumerate(files):
            temp_file_path = None
            try:
                display_name = names_list[idx] if idx < len(names_list) and names_list[idx] is not None else None
                metadata_dict = {}
                if idx < len(meta_list) and meta_list[idx] is not None:
                    if not isinstance(meta_list[idx], dict):
                        raise ValueError(f"Metadata at index {idx} must be a JSON object (dict)")
                    metadata_dict = meta_list[idx]

                temp_file_path = await self._write_temp_upload(file)
                progress_callback = self._build_progress_callback(client_id)
                file_doc, bg_payload = await self._file_service.upload_file_quick(
                    file_path=temp_file_path,
                    original_filename=file.filename,
                    display_name=display_name,
                    custom_metadata=metadata_dict,
                    progress_callback=progress_callback,
                )
                background_tasks.append(
                    FileBackgroundTask(
                        file_id=bg_payload["file_id"],
                        file_path=temp_file_path,
                        display_name=bg_payload["display_name"],
                        custom_metadata=bg_payload["custom_metadata"],
                        progress_callback=progress_callback,
                    )
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
            except Exception as exc:
                logger.error("Failed to upload file %s: %s", file.filename, exc)
                results.append(BatchFileUploadResult(original_filename=file.filename, success=False, error=str(exc)))
                failed += 1
                if temp_file_path and os.path.exists(temp_file_path):
                    try:
                        os.unlink(temp_file_path)
                    except Exception as unlink_err:
                        logger.warning("Failed to clean up temp file on error: %s", unlink_err)

        return BatchUploadOutcome(
            response=BatchFileUploadResponse(
                total=len(files),
                successful=successful,
                failed=failed,
                results=results,
            ),
            background_tasks=background_tasks,
        )

    async def get_file_detail(self, file_id: str, user: JWTPayload) -> FileDetailResponse:
        file_doc = await self._file_service.get_file_by_id(file_id)
        if not file_doc:
            raise NotFoundException("File", file_id)
        self._ensure_read_access(file_doc, user)
        return self.to_file_detail_response(file_doc)

    async def update_file(self, file_id: str, request: UpdateFileRequest) -> FileDetailResponse:
        file_doc = await self._file_service.update_file(
            file_id=file_id,
            display_name=request.display_name,
            custom_metadata=(
                request.custom_metadata.model_dump(exclude_unset=True, by_alias=False)
                if request.custom_metadata
                else None
            ),
            lecturer_only=request.lecturer_only,
        )
        if not file_doc:
            raise NotFoundException("File", file_id)
        return self.to_file_detail_response(file_doc)

    async def delete_file(self, file_id: str, deleted_by: str) -> None:
        await self._file_service.delete_file(file_id, deleted_by)

    async def restore_file(self, file_id: str) -> FileDetailResponse:
        return self.to_file_detail_response(await self._file_service.restore_file(file_id))

    async def purge_file(self, file_id: str) -> None:
        await self._file_service.purge_file(file_id)

    async def download_file(self, file_id: str, requested_format: str, user: JWTPayload):
        allowed_formats = {"original", "markdown"}
        file_format = requested_format.lower()
        if file_format not in allowed_formats:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid format. Allowed values: original, markdown",
            )
        file_doc = await self._file_service.get_file_by_id(file_id)
        if not file_doc:
            raise NotFoundException("File", file_id)
        self._ensure_read_access(file_doc, user)
        return await self._file_service.download_file(file_id, file_format=file_format)

    @staticmethod
    def _ensure_read_access(file_doc, user: JWTPayload) -> None:
        """Hide non-ready lifecycle records from non-admin users."""
        file_status = file_doc.status.value if hasattr(file_doc.status, "value") else str(file_doc.status)
        if user.role != "admin" and file_status != FileStatus.READY.value:
            raise NotFoundException("File", str(file_doc.id))
        if user.role not in ("admin", "lecture") and bool(file_doc.lecturer_only):
            raise NotFoundException("File", str(file_doc.id))

    @staticmethod
    def to_file_list_item_response(file_doc) -> FileListItemResponse:
        return FileListItemResponse(
            file_id=str(file_doc.id),
            original_filename=file_doc.original_filename,
            display_name=file_doc.display_name,
            file_size=file_doc.file_size,
            mime_type=file_doc.mime_type,
            storage_path=file_doc.storage_path,
            status=file_doc.status.value if hasattr(file_doc.status, "value") else str(file_doc.status),
            lecturer_only=bool(file_doc.lecturer_only),
            custom_metadata=FileMetadataResponse.from_model(file_doc.custom_metadata) if file_doc.custom_metadata else None,
            file_url=get_download_url(file_doc.storage_path),
            markdown_file_url=get_download_url(file_doc.markdown_storage_path) if file_doc.markdown_storage_path else None,
            created_at=file_doc.created_at.isoformat() if file_doc.created_at else "",
            updated_at=file_doc.updated_at.isoformat() if file_doc.updated_at else "",
            deleted_at=file_doc.deleted_at.isoformat() if getattr(file_doc, "deleted_at", None) else None,
            deleted_by=getattr(file_doc, "deleted_by", None),
        )

    @staticmethod
    def to_file_detail_response(file_doc) -> FileDetailResponse:
        return FileDetailResponse(
            file_id=str(file_doc.id),
            original_filename=file_doc.original_filename,
            display_name=file_doc.display_name,
            file_size=file_doc.file_size,
            mime_type=file_doc.mime_type,
            storage_path=file_doc.storage_path,
            status=file_doc.status.value if hasattr(file_doc.status, "value") else str(file_doc.status),
            lecturer_only=file_doc.lecturer_only,
            custom_metadata=FileMetadataResponse.from_model(file_doc.custom_metadata) if file_doc.custom_metadata else None,
            file_url=get_download_url(file_doc.storage_path),
            markdown_file_url=get_download_url(file_doc.markdown_storage_path) if file_doc.markdown_storage_path else None,
            table_of_contents=file_doc.table_of_contents,
            created_at=file_doc.created_at.isoformat() if file_doc.created_at else "",
            updated_at=file_doc.updated_at.isoformat() if file_doc.updated_at else "",
            deleted_at=file_doc.deleted_at.isoformat() if getattr(file_doc, "deleted_at", None) else None,
            deleted_by=getattr(file_doc, "deleted_by", None),
        )

    async def process_background_task(self, task: FileBackgroundTask) -> None:
        await self._file_service.process_file_background(
            file_id=task.file_id,
            file_path=task.file_path,
            display_name=task.display_name,
            custom_metadata=task.custom_metadata,
            progress_callback=task.progress_callback,
        )

    @staticmethod
    async def _write_temp_upload(file: UploadFile) -> str:
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file.filename)[1], mode="wb") as temp_file:
            contents = await file.read()
            temp_file.write(contents)
            return temp_file.name

    @staticmethod
    def _parse_json_object(raw: str | None, *, field_name: str) -> dict[str, Any]:
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid {field_name} JSON format") from exc
        if not isinstance(parsed, dict):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"{field_name} must be a JSON object")
        return parsed

    @staticmethod
    def _parse_json_list(raw: str | None, *, field_name: str) -> list[Any]:
        if not raw:
            return []
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid {field_name} JSON") from exc
        if not isinstance(parsed, list):
            raise HTTPException(status_code=400, detail=f"{field_name} must be a list")
        return parsed

    @staticmethod
    def _build_role_filter(user: JWTPayload) -> dict[str, Any] | None:
        if user.role in ("admin", "lecture"):
            return None
        role_filter: dict[str, Any] = {"lecturer_only": {"$ne": True}}
        if user.enrollment_year:
            enrollment_year = user.enrollment_year
            role_filter["$and"] = [{"$or": [
                {"custom_metadata.enrollment_year_from": {"$exists": False}},
                {
                    "custom_metadata.enrollment_year_from": {"$lte": enrollment_year},
                    "custom_metadata.enrollment_year_to": {"$gte": enrollment_year},
                },
            ]}]
        return role_filter

    @staticmethod
    def _build_progress_callback(client_id: str | None):
        notifier = get_file_status_notifier()

        async def _progress_callback(payload: dict[str, Any]):
            if client_id:
                await notifier.notify(client_id, payload)

        return _progress_callback


_file_api_service_instance: Optional[FileApiService] = None


def get_file_api_service() -> FileApiService:
    global _file_api_service_instance
    if _file_api_service_instance is None:
        _file_api_service_instance = FileApiService()
    return _file_api_service_instance
