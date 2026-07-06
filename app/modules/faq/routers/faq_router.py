from fastapi import APIRouter, Depends, HTTPException, Query, status, File, UploadFile
from typing import Optional
import json
import re

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
    FaqImportPreviewResponse,
    FaqBulkCreateRequest,
    FaqBulkCreateResponse,
    FaqBulkCreateItem,
    FaqImportExcelRequest
)
from app.modules.faq.services.faq_service import get_faq_service, FaqService
from app.modules.faq.services.faq_synthesizer_service import get_faq_synthesis_service
from app.modules.faq.utils.excel_parser import parse_excel_to_faq_rows, parse_csv_to_faq_rows
from app.modules.metadata.dtos.update_metadata import FaqMetadataSchema
from app.modules.metadata.services.metadata_service import get_metadata_service
from app.core.exceptions import handle_google_api_error
from google.genai.errors import APIError

router = APIRouter(prefix="/faqs", tags=["FAQ"])


# ==========================================
# Public FAQ Endpoints (Auth Required)
# ==========================================
@router.get("", response_model=FaqListResponse)
async def list_faqs(
    is_active: Optional[bool] = Query(None, alias="isActive", description="Filter by active status"),
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
        is_active=is_active,
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
@router.post("", response_model=FaqResponse, status_code=status.HTTP_201_CREATED)
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


@router.post("/match", response_model=FaqResponse)
async def debug_match_faq(
    request: FaqMatchRequest,
    admin: JWTPayload = Depends(require_admin),
    faq_svc: FaqService = Depends(get_faq_service)
):
    """Debug endpoint to test vectorless FAQ matching."""
    meta = request.metadata_filter.model_dump(by_alias=False) if request.metadata_filter else {}
    faq = await faq_svc.find_best_match(request.question, meta, threshold=request.threshold)
    if not faq:
        raise HTTPException(status_code=404, detail="No matching FAQ found above threshold")
    return FaqResponse.from_document(faq)


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
    synth_svc = await get_faq_synthesis_service()
    
    try:
        result = await synth_svc.run(
            date_from_str=request.date_from,
            date_to_str=request.date_to,
            sources=request.sources
        )
        return FaqSynthesisResponse(**result)
    except Exception as e:
        if isinstance(e, APIError):
            raise handle_google_api_error(e, prefix="Synthesis failed: ")
            
        raise HTTPException(status_code=500, detail=f"Synthesis failed: {str(e)}")


@router.patch("/{faq_id}", response_model=FaqResponse)
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
    success = await faq_svc.delete_faq(faq_id)
    if not success:
        raise HTTPException(status_code=404, detail="FAQ not found")


@router.get("/{faq_id}", response_model=FaqResponse)
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
    try:
        metadata_map = json.loads(req.metadata_filter_json) if req.metadata_filter_json else {}
        if not isinstance(metadata_map, dict):
            raise HTTPException(status_code=400, detail="metadata_filter_json must be a JSON object")
        allowed_keys = set()
        for name, field in FaqMetadataSchema.model_fields.items():
            allowed_keys.add(name)
            if field.alias:
                allowed_keys.add(field.alias)
            camel = re.sub(r'_([a-z])', lambda match: match.group(1).upper(), name)
            allowed_keys.add(camel)
            
        for k in metadata_map.keys():
            if k not in allowed_keys:
                raise HTTPException(status_code=400, detail=f"Invalid metadata key: {k}")
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"Invalid metadata_filter_json: {e}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid FAQ metadata: {e}")
        
    content = await file.read()
    try:
        if file.filename and file.filename.lower().endswith('.csv'):
            result = parse_csv_to_faq_rows(
                file_bytes=content,
                question_col=req.question_col,
                answer_col=req.answer_col,
                metadata_map=metadata_map,
                skip_rows=req.skip_rows
            )
        else:
            result = parse_excel_to_faq_rows(
                file_bytes=content,
                question_col=req.question_col,
                answer_col=req.answer_col,
                metadata_map=metadata_map,
                sheet_name=req.sheet_name,
                skip_rows=req.skip_rows
            )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/import", response_model=FaqBulkCreateResponse)
async def import_faqs_from_excel(
    file: UploadFile = File(...),
    req: FaqImportExcelRequest = Depends(from_form(FaqImportExcelRequest)),
    admin: JWTPayload = Depends(require_admin),
    faq_svc: FaqService = Depends(get_faq_service)
):
    """
    Upload Excel and create FAQs in bulk.
    """
    try:
        metadata_map = json.loads(req.metadata_filter_json) if req.metadata_filter_json else {}
        if not isinstance(metadata_map, dict):
            raise HTTPException(status_code=400, detail="metadata_filter_json must be a JSON object")
        allowed_keys = set()
        for name, field in FaqMetadataSchema.model_fields.items():
            allowed_keys.add(name)
            if field.alias:
                allowed_keys.add(field.alias)
            camel = re.sub(r'_([a-z])', lambda match: match.group(1).upper(), name)
            allowed_keys.add(camel)
            
        for k in metadata_map.keys():
            if k not in allowed_keys:
                raise HTTPException(status_code=400, detail=f"Invalid metadata key: {k}")
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"Invalid metadata_filter_json: {e}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid FAQ metadata: {e}")
        
    content = await file.read()
    try:
        if file.filename and file.filename.lower().endswith('.csv'):
            parsed = parse_csv_to_faq_rows(
                file_bytes=content,
                question_col=req.question_col,
                answer_col=req.answer_col,
                metadata_map=metadata_map,
                skip_rows=req.skip_rows
            )
        else:
            parsed = parse_excel_to_faq_rows(
                file_bytes=content,
                question_col=req.question_col,
                answer_col=req.answer_col,
                metadata_map=metadata_map,
                sheet_name=req.sheet_name,
                skip_rows=req.skip_rows
            )
        
        valid_items = [
            FaqBulkCreateItem(
                question=r["question"],
                answer_rich_text=r["answer_rich_text"],
                metadata_filter=r["metadata"],
                lecturer_only=req.lecturer_only,
            )
            for r in parsed["rows"] if r["is_valid"]
        ]
        
        result = await faq_svc.bulk_create_faqs(valid_items, skip_duplicates=req.skip_duplicates)
        
        parser_errors = [
            {"row_index": r["row_index"], "question": r["question"], "error": r["error"]}
            for r in parsed["rows"] if not r["is_valid"]
        ]
        result["errors"].extend(parser_errors)
        result["failed"] += len(parser_errors)
        
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


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
