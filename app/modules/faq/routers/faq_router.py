from fastapi import APIRouter, Depends, HTTPException, Query, status, File, UploadFile
from typing import Optional

from app.core.auth import JWTPayload
from app.core.dependencies import require_admin, require_auth, from_form
from app.modules.faq.dtos import (
    FaqCreateRequest,
    FaqUpdateRequest,
    FaqResponse,
    FaqListResponse,
    FaqCandidateResponse,
    FaqCandidateListResponse,
    FaqReviewRequest,
    FaqSynthesisRequest,
    FaqSynthesisResponse,
    FaqMatchRequest,
    FaqMatchResponse,
    FaqImportPreviewResponse,
    FaqBulkCreateRequest,
    FaqBulkCreateResponse,
    FaqImportExcelRequest
)
from app.modules.faq.services.faq_service import get_faq_service, FaqService
from app.modules.faq.services.faq_import_service import get_faq_import_service
from app.modules.metadata.services.metadata_service import get_metadata_service
from app.core.exceptions import handle_google_api_error
from google.genai.errors import APIError
import json

router = APIRouter(prefix="/faqs", tags=["FAQ"])


# ==========================================
# Public FAQ Endpoints (Auth Required)
# ==========================================
@router.get("", response_model=FaqListResponse, response_model_exclude_none=True)
async def list_faqs(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    metadata_filter: Optional[str] = Query(None, alias="metadataFilter", description="Filter by metadata (JSON string), e.g. {'academic_year': ['2024-2025']}"),
    search: Optional[str] = Query(None, description="Search by question text"),
    user: JWTPayload = Depends(require_auth),
    faq_svc: FaqService = Depends(get_faq_service)
):
    """List FAQs with optional filtering."""
    meta = None
    if metadata_filter:
        try:
            meta = json.loads(metadata_filter)
            metadata_svc = get_metadata_service()
            is_valid, errors, _ = metadata_svc.validate_and_parse_faq_metadata(meta)
            if not is_valid:
                raise HTTPException(status_code=400, detail=f"Invalid metadataFilter: {', '.join(errors)}")
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Invalid metadataFilter JSON")

    result = await faq_svc.list_faqs(
        metadata_filter=meta,
        search=search,
        page=page,
        limit=limit,
        exclude_lecturer_only=user.role not in ("admin", "lecture"),
    )
    return FaqListResponse(
        items=[FaqResponse.from_document(item) for item in result.items],
        total=result.total,
        page=result.page,
        limit=result.limit
    )


# ==========================================
# Admin FAQ Endpoints (Admin Required)
# ==========================================
@router.post("", response_model=FaqResponse, response_model_exclude_none=True, status_code=status.HTTP_201_CREATED)
async def create_faq(
    request: FaqCreateRequest,
    admin: JWTPayload = Depends(require_admin),
    faq_svc: FaqService = Depends(get_faq_service)
):
    """Create a new FAQ manually."""
    result = await faq_svc.create_faq(
        question=request.question,
        answer_rich_text=request.answer_rich_text,
        metadata_filter=request.metadata_filter.model_dump(by_alias=False) if request.metadata_filter else {},
        source="manual",
        lecturer_only=request.lecturer_only,
    )
    return FaqResponse.from_document(result)


@router.get(
    "/trash",
    response_model=FaqListResponse,
    response_model_exclude_none=True,
    summary="List soft-deleted FAQs",
)
async def list_deleted_faqs(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    metadata_filter: Optional[str] = Query(None, alias="metadataFilter"),
    search: Optional[str] = Query(None),
    admin: JWTPayload = Depends(require_admin),
    faq_svc: FaqService = Depends(get_faq_service),
):
    meta = None
    if metadata_filter:
        try:
            meta = json.loads(metadata_filter)
            is_valid, errors, _ = get_metadata_service().validate_and_parse_faq_metadata(meta)
            if not is_valid:
                raise HTTPException(status_code=400, detail=f"Invalid metadataFilter: {', '.join(errors)}")
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail="Invalid metadataFilter JSON") from exc

    result = await faq_svc.list_deleted_faqs(
        metadata_filter=meta,
        search=search,
        page=page,
        limit=limit,
    )
    return FaqListResponse(
        items=[FaqResponse.from_document(item) for item in result.items],
        total=result.total,
        page=result.page,
        limit=result.limit,
    )


@router.post("/match", response_model=FaqMatchResponse)
async def debug_match_faq(
    request: FaqMatchRequest,
    admin: JWTPayload = Depends(require_admin),
    faq_svc: FaqService = Depends(get_faq_service)
):
    """Debug endpoint to test FAQ-based answering."""
    meta = request.metadata_filter.model_dump(by_alias=False) if request.metadata_filter else {}
    result = await faq_svc.answer_from_faq_catalog(
        request.question,
        meta,
        increment_view_count=False,
    )
    if not result:
        raise HTTPException(status_code=404, detail="No matching FAQ found")
    return FaqMatchResponse(
        answer_markdown=result.answer_markdown,
        faq_ids=[str(getattr(faq, "id", "")) for faq in result.matched_faqs],
        questions=[getattr(faq, "question", "") for faq in result.matched_faqs],
    )


# ==========================================
# Admin Candidate Endpoints
# ==========================================
@router.get("/candidates/list", response_model=FaqCandidateListResponse)
async def list_candidates(
    status_filter: Optional[str] = Query(None, alias="status", description="Filter by status (pending, approved, rejected). If not provided, returns all."),
    search: Optional[str] = Query(None, description="Search keyword for candidates"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    admin: JWTPayload = Depends(require_admin),
    faq_svc: FaqService = Depends(get_faq_service)
):
    """List FAQ candidates from synthesis."""
    result = await faq_svc.list_candidates(status=status_filter, search=search, page=page, limit=limit)
    return FaqCandidateListResponse(
        items=[FaqCandidateResponse.from_document(item) for item in result.items],
        total=result.total,
        page=result.page,
        limit=result.limit
    )


@router.get("/candidates/{candidate_id}", response_model=FaqCandidateResponse)
async def get_candidate(
    candidate_id: str,
    admin: JWTPayload = Depends(require_admin),
    faq_svc: FaqService = Depends(get_faq_service)
):
    """Get a specific FAQ candidate by ID."""
    candidate = await faq_svc.get_candidate(candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")
    return FaqCandidateResponse.from_document(candidate)


@router.post("/candidates/{candidate_id}/review", response_model=FaqCandidateResponse)
async def review_candidate(
    candidate_id: str,
    request: FaqReviewRequest,
    admin: JWTPayload = Depends(require_admin),
    faq_svc: FaqService = Depends(get_faq_service)
):
    """Approve or reject an FAQ candidate."""
    try:
        result = await faq_svc.review_candidate(
            candidate_id=candidate_id,
            action=request.action,
            reviewer_id=admin.user_id,
            question_override=request.question_override,
            answer_rich_text_override=request.answer_rich_text_override,
            metadata_filter_override=request.metadata_filter_override.model_dump(by_alias=False) if request.metadata_filter_override else None,
            note=request.note
        )
        return FaqCandidateResponse.from_document(result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/synthesis", response_model=FaqSynthesisResponse)
async def trigger_synthesis(
    request: FaqSynthesisRequest,
    admin: JWTPayload = Depends(require_admin)
):
    """Manually trigger FAQ synthesis background job."""
    raise HTTPException(
        status_code=501,
        detail="FAQ synthesis is temporarily disabled pending architecture migration"
    )


@router.patch("/{faq_id}", response_model=FaqResponse, response_model_exclude_none=True)
async def update_faq(
    faq_id: str,
    request: FaqUpdateRequest,
    admin: JWTPayload = Depends(require_admin),
    faq_svc: FaqService = Depends(get_faq_service)
):
    """Update an existing FAQ."""
    update_data = request.model_dump(exclude_unset=True, by_alias=False)
    if "metadata_filter" in update_data and update_data["metadata_filter"] is not None:
        update_data["metadata_filter"] = request.metadata_filter.model_dump(by_alias=False)

    result = await faq_svc.update_faq(faq_id, update_data)
    if not result:
        raise HTTPException(status_code=404, detail="FAQ not found")
    return FaqResponse.from_document(result)


@router.delete("/{faq_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_faq(
    faq_id: str,
    admin: JWTPayload = Depends(require_admin),
    faq_svc: FaqService = Depends(get_faq_service)
):
    """Delete an FAQ."""
    success = await faq_svc.delete_faq(faq_id, admin.user_id)
    if not success:
        raise HTTPException(status_code=404, detail="FAQ not found")


@router.post(
    "/{faq_id}/restore",
    response_model=FaqResponse,
    response_model_exclude_none=True,
    summary="Restore a soft-deleted FAQ",
)
async def restore_faq(
    faq_id: str,
    admin: JWTPayload = Depends(require_admin),
    faq_svc: FaqService = Depends(get_faq_service),
):
    return FaqResponse.from_document(await faq_svc.restore_faq(faq_id))


@router.delete(
    "/{faq_id}/purge",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Permanently purge a soft-deleted FAQ",
)
async def purge_faq(
    faq_id: str,
    admin: JWTPayload = Depends(require_admin),
    faq_svc: FaqService = Depends(get_faq_service),
):
    await faq_svc.purge_faq(faq_id)


@router.get("/{faq_id}", response_model=FaqResponse, response_model_exclude_none=True)
async def get_faq(
    faq_id: str,
    user: JWTPayload = Depends(require_auth),
    faq_svc: FaqService = Depends(get_faq_service)
):
    """Get a specific FAQ by ID."""
    faq = await faq_svc.get_faq(faq_id)
    if not faq:
        raise HTTPException(status_code=404, detail="FAQ not found")
    if faq.lecturer_only and user.role not in ("admin", "lecture"):
        # Student xin FAQ lecturer_only → coi như không tồn tại
        raise HTTPException(status_code=404, detail="FAQ not found")
    return FaqResponse.from_document(faq)


# --- Bulk Import Endpoints ---

@router.post("/import/preview", response_model=FaqImportPreviewResponse)
async def preview_faq_import(
    file: UploadFile = File(...),
    req: FaqImportExcelRequest = Depends(from_form(FaqImportExcelRequest)),
    admin: JWTPayload = Depends(require_admin)
):
    """
    Upload Excel and preview extracted FAQ rows.
    """
    content = await file.read()
    return await get_faq_import_service().preview_import(
        filename=file.filename,
        file_bytes=content,
        request=req,
    )


@router.post("/import", response_model=FaqBulkCreateResponse)
async def import_faqs_from_excel(
    file: UploadFile = File(...),
    req: FaqImportExcelRequest = Depends(from_form(FaqImportExcelRequest)),
    admin: JWTPayload = Depends(require_admin),
):
    """
    Upload Excel and create FAQs in bulk.
    """
    content = await file.read()
    return await get_faq_import_service().import_faqs(
        filename=file.filename,
        file_bytes=content,
        request=req,
    )


@router.post("/bulk", response_model=FaqBulkCreateResponse)
async def bulk_create_faqs_json(
    request: FaqBulkCreateRequest,
    admin: JWTPayload = Depends(require_admin),
    faq_svc: FaqService = Depends(get_faq_service)
):
    """
    Bulk create FAQs from JSON data.
    """
    return await faq_svc.bulk_create_faqs(request.items, skip_duplicates=request.skip_duplicates)
