from fastapi import APIRouter, Depends, HTTPException, Query, status, UploadFile, File, Form
from typing import Optional

from app.core.auth import JWTPayload
from app.core.dependencies import require_admin, require_auth
from app.modules.forms.dtos import (
    FormCreateRequest,
    FormUpdateRequest,
    FormResponse,
    FormListResponse,
    FormImportPreviewResponse,
    FormBulkCreateResponse
)
from app.modules.forms.services.form_service import get_form_service, FormService
from app.modules.forms.services.form_import_service import get_form_import_service

router = APIRouter(prefix="/forms", tags=["Forms"])

@router.get("", response_model=FormListResponse)
async def list_forms(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    search: Optional[str] = Query(None),
    user: JWTPayload = Depends(require_auth),
    form_svc: FormService = Depends(get_form_service)
):
    result = await form_svc.list_forms(page=page, limit=limit, search=search)
    return FormListResponse(
        items=[FormResponse.from_document(item) for item in result.items],
        pagination={
            "total": result.total,
            "current_page": result.page,
            "limit": result.limit,
            "total_pages": result.total_pages
        }
    )

@router.get("/{form_id}", response_model=FormResponse)
async def get_form(
    form_id: str,
    user: JWTPayload = Depends(require_auth),
    form_svc: FormService = Depends(get_form_service)
):
    form = await form_svc.get_form_by_id(form_id)
    if not form:
        raise HTTPException(status_code=404, detail="Form not found")
    return FormResponse.from_document(form)

@router.post("", response_model=FormResponse, status_code=status.HTTP_201_CREATED)
async def create_form(
    request: FormCreateRequest,
    admin: JWTPayload = Depends(require_admin),
    form_svc: FormService = Depends(get_form_service)
):
    result = await form_svc.create_form(
        document_type=request.document_type,
        content_link=request.content_link,
        notes=request.notes
    )
    return FormResponse.from_document(result)

@router.put("/{form_id}", response_model=FormResponse)
async def update_form(
    form_id: str,
    request: FormUpdateRequest,
    admin: JWTPayload = Depends(require_admin),
    form_svc: FormService = Depends(get_form_service)
):
    result = await form_svc.update_form(
        form_id=form_id,
        document_type=request.document_type,
        content_link=request.content_link,
        notes=request.notes
    )
    if not result:
        raise HTTPException(status_code=404, detail="Form not found")
    return FormResponse.from_document(result)

@router.delete("/{form_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_form(
    form_id: str,
    admin: JWTPayload = Depends(require_admin),
    form_svc: FormService = Depends(get_form_service)
):
    deleted = await form_svc.delete_form(form_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Form not found")
        
@router.post("/import-preview", response_model=FormImportPreviewResponse)
async def import_preview(
    file: UploadFile = File(...),
    start_row: str = Form("2"),
    document_type_col: str = Form("1"),
    content_link_col: str = Form("2"),
    notes_col: Optional[str] = Form("3"),
    admin: JWTPayload = Depends(require_admin),
):
    content = await file.read()
    return await get_form_import_service().preview_import(
        filename=file.filename,
        file_bytes=content,
        start_row=start_row,
        document_type_col=document_type_col,
        content_link_col=content_link_col,
        notes_col=notes_col,
    )

@router.post("/import", response_model=FormBulkCreateResponse)
async def import_forms(
    file: UploadFile = File(...),
    start_row: str = Form("2"),
    document_type_col: str = Form("1"),
    content_link_col: str = Form("2"),
    notes_col: Optional[str] = Form("3"),
    admin: JWTPayload = Depends(require_admin),
):
    content = await file.read()
    return await get_form_import_service().import_forms(
        filename=file.filename,
        file_bytes=content,
        start_row=start_row,
        document_type_col=document_type_col,
        content_link_col=content_link_col,
        notes_col=notes_col,
    )
