"""
FastAPI Router for FAQ Module.
"""
from fastapi import APIRouter, Depends, HTTPException, Query, status, File, UploadFile, Form
from typing import List, Optional, Dict, Any

from app.core.dependencies import require_admin, require_auth
from app.modules.faq.schemas import (
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
    FaqBulkCreateResponse
)
from app.modules.faq.service import get_faq_service, FaqService
from app.modules.faq.synthesizer import get_faq_synthesis_service
from app.modules.faq.excel_parser import parse_excel_to_faq_rows

router = APIRouter(prefix="/faqs", tags=["FAQ"])


# ==========================================
# Public FAQ Endpoints (Auth Required)
# ==========================================
@router.get("", response_model=FaqListResponse)
async def list_faqs(
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    metadata_filter: Optional[str] = Query(None, alias="metadataFilter", description="Filter by metadata (JSON string), e.g. {'academic_year': ['2024-2025']}"),
    search: Optional[str] = Query(None, description="Search by question text"),
    user: Dict[str, Any] = Depends(require_auth),
    faq_svc: FaqService = Depends(get_faq_service)
):
    """List FAQs with optional filtering."""
    import json
    meta = None
    if metadata_filter:
        try:
            meta = json.loads(metadata_filter)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Invalid metadataFilter JSON")

    result = await faq_svc.list_faqs(
        is_active=is_active,
        metadata_filter=meta,
        search=search,
        page=page,
        limit=limit
    )
    return FaqListResponse(
        items=[FaqResponse.from_mongo(item) for item in result["items"]],
        total=result["total"],
        page=result["page"],
        limit=result["limit"]
    )


# ==========================================
# Admin FAQ Endpoints (Admin Required)
# ==========================================
@router.post("", response_model=FaqResponse, status_code=status.HTTP_201_CREATED)
async def create_faq(
    request: FaqCreateRequest,
    admin: Dict[str, Any] = Depends(require_admin),
    faq_svc: FaqService = Depends(get_faq_service)
):
    """Create a new FAQ manually."""
    result = await faq_svc.create_faq(
        question=request.question,
        answer_rich_text=request.answer_rich_text,
        metadata_filter=request.metadata_filter.model_dump(by_alias=False) if request.metadata_filter else {},
        source="manual"
    )
    return FaqResponse.from_mongo(result)


@router.post("/match", response_model=FaqResponse)
async def debug_match_faq(
    request: FaqMatchRequest,
    admin: Dict[str, Any] = Depends(require_admin),
    faq_svc: FaqService = Depends(get_faq_service)
):
    """Debug endpoint to test semantic matching."""
    vector = await faq_svc.embed(request.question)
    meta = request.metadata_filter.model_dump(by_alias=False) if request.metadata_filter else {}
    
    faq = await faq_svc.find_best_match(vector, meta, threshold=request.threshold)
    if not faq:
        raise HTTPException(status_code=404, detail="No matching FAQ found above threshold")
    return FaqResponse.from_mongo(faq)


# ==========================================
# Admin Candidate Endpoints
# ==========================================
@router.get("/candidates/list", response_model=FaqCandidateListResponse)
async def list_candidates(
    status_filter: Optional[str] = Query(None, alias="status", description="Filter by status (pending, approved, rejected). If not provided, returns all."),
    search: Optional[str] = Query(None, description="Search keyword for candidates"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    admin: Dict[str, Any] = Depends(require_admin),
    faq_svc: FaqService = Depends(get_faq_service)
):
    """List FAQ candidates from synthesis."""
    result = await faq_svc.list_candidates(status=status_filter, search=search, page=page, limit=limit)
    return FaqCandidateListResponse(
        items=[FaqCandidateResponse.from_mongo(item) for item in result["items"]],
        total=result["total"],
        page=result["page"],
        limit=result["limit"]
    )


@router.get("/candidates/{candidate_id}", response_model=FaqCandidateResponse)
async def get_candidate(
    candidate_id: str,
    admin: Dict[str, Any] = Depends(require_admin),
    faq_svc: FaqService = Depends(get_faq_service)
):
    """Get a specific FAQ candidate by ID."""
    candidate = await faq_svc.get_candidate(candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")
    return FaqCandidateResponse.from_mongo(candidate)


@router.post("/candidates/{candidate_id}/review", response_model=FaqCandidateResponse)
async def review_candidate(
    candidate_id: str,
    request: FaqReviewRequest,
    admin: Dict[str, Any] = Depends(require_admin),
    faq_svc: FaqService = Depends(get_faq_service)
):
    """Approve or reject an FAQ candidate."""
    try:
        result = await faq_svc.review_candidate(
            candidate_id=candidate_id,
            action=request.action,
            reviewer_id=admin.get("user_id", "admin"),
            question_override=request.question_override,
            answer_rich_text_override=request.answer_rich_text_override,
            metadata_filter_override=request.metadata_filter_override.model_dump(by_alias=False) if request.metadata_filter_override else None,
            note=request.note
        )
        return FaqCandidateResponse.from_mongo(result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/synthesis", response_model=FaqSynthesisResponse)
async def trigger_synthesis(
    request: FaqSynthesisRequest,
    admin: Dict[str, Any] = Depends(require_admin)
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
        raise HTTPException(status_code=500, detail=f"Synthesis failed: {str(e)}")


@router.patch("/{faq_id}", response_model=FaqResponse)
async def update_faq(
    faq_id: str,
    request: FaqUpdateRequest,
    admin: Dict[str, Any] = Depends(require_admin),
    faq_svc: FaqService = Depends(get_faq_service)
):
    """Update an existing FAQ."""
    update_data = request.model_dump(exclude_unset=True, by_alias=False)
    if "metadata_filter" in update_data and update_data["metadata_filter"] is not None:
        # Convert Pydantic model to dict if it's not already
        update_data["metadata_filter"] = request.metadata_filter.model_dump(by_alias=False)

    result = await faq_svc.update_faq(faq_id, update_data)
    if not result:
        raise HTTPException(status_code=404, detail="FAQ not found")
    return FaqResponse.from_mongo(result)


@router.delete("/{faq_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_faq(
    faq_id: str,
    admin: Dict[str, Any] = Depends(require_admin),
    faq_svc: FaqService = Depends(get_faq_service)
):
    """Delete an FAQ."""
    success = await faq_svc.delete_faq(faq_id)
    if not success:
        raise HTTPException(status_code=404, detail="FAQ not found")


@router.get("/{faq_id}", response_model=FaqResponse)
async def get_faq(
    faq_id: str,
    user: Dict[str, Any] = Depends(require_auth),
    faq_svc: FaqService = Depends(get_faq_service)
):
    """Get a specific FAQ by ID."""
    faq = await faq_svc.get_faq(faq_id)
    if not faq:
        raise HTTPException(status_code=404, detail="FAQ not found")
    return FaqResponse.from_mongo(faq)


# --- Bulk Import Endpoints ---

@router.post("/import/preview", response_model=FaqImportPreviewResponse)
async def preview_faq_import(
    file: UploadFile = File(...),
    question_col: str = Form(...),
    answer_col: str = Form(...),
    metadata_filter_json: str = Form(..., alias="metadataFilterJson", description="JSON string mapping columns to metadata keys"),
    sheet_name: Optional[str] = Form(None),
    skip_rows: int = Form(1),
    admin: Dict[str, Any] = Depends(require_admin)
):
    """
    Upload Excel and preview extracted FAQ rows.
    """
    import json
    metadata_map = json.loads(metadata_filter_json)
    content = await file.read()
    try:
        result = parse_excel_to_faq_rows(
            file_bytes=content,
            question_col=question_col,
            answer_col=answer_col,
            metadata_map=metadata_map,
            sheet_name=sheet_name,
            skip_rows=skip_rows
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/import", response_model=FaqBulkCreateResponse)
async def import_faqs_from_excel(
    file: UploadFile = File(...),
    question_col: str = Form(...),
    answer_col: str = Form(...),
    metadata_filter_json: str = Form(..., alias="metadataFilterJson", description="JSON string mapping columns to metadata keys"),
    sheet_name: Optional[str] = Form(None),
    skip_rows: int = Form(1),
    skip_duplicates: bool = Form(True),
    admin: Dict[str, Any] = Depends(require_admin),
    faq_svc: FaqService = Depends(get_faq_service)
):
    """
    Upload Excel and create FAQs in bulk.
    """
    import json
    metadata_map = json.loads(metadata_filter_json)
    content = await file.read()
    try:
        # 1. Parse
        parsed = parse_excel_to_faq_rows(
            file_bytes=content,
            question_col=question_col,
            answer_col=answer_col,
            metadata_map=metadata_map,
            sheet_name=sheet_name,
            skip_rows=skip_rows
        )
        
        # 2. Filter valid rows
        valid_items = [
            {
                "question": r["question"],
                "answer_rich_text": r["answer_rich_text"],
                "metadata_filter": r["metadata"]
            }
            for r in parsed["rows"] if r["is_valid"]
        ]
        
        # 3. Create
        result = await faq_svc.bulk_create_faqs(valid_items, skip_duplicates=skip_duplicates)
        
        # 4. Merge errors from parser
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
    admin: Dict[str, Any] = Depends(require_admin),
    faq_svc: FaqService = Depends(get_faq_service)
):
    """
    Bulk create FAQs from JSON data.
    """
    items = [item.model_dump(by_alias=False) for item in request.items]
    return await faq_svc.bulk_create_faqs(items, skip_duplicates=request.skip_duplicates)

