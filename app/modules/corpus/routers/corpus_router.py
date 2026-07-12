from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status

from app.core.auth import JWTPayload
from app.core.dependencies import require_admin
from app.modules.corpus.dtos import (
    BackfillStartResponse,
    CorpusNodeListResponse,
    CorpusNodeResponse,
    CorpusPayloadTopicsResponse,
    CorpusStatsResponse,
    TopicCreateRequest,
    TopicDeleteResponse,
    TopicMergeRequest,
    TopicMergeResponse,
    CorpusTreeResponse,
    TopicUpdateRequest,
    PayloadTopicsUpdateRequest,
)
from app.modules.corpus.services.corpus_job_service import get_corpus_job_service
from app.modules.corpus.services.corpus_service import get_corpus_service

router = APIRouter(prefix="/corpus", tags=["Corpus"])

def _http_error(exc: ValueError) -> HTTPException:
    message = str(exc)
    if "not found" in message.lower():
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message)
    if "already exists" in message.lower():
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=message)
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message)


@router.get("/stats", response_model=CorpusStatsResponse, summary="Corpus tree statistics")
async def corpus_stats(_admin: JWTPayload = Depends(require_admin)):
    return await get_corpus_service().get_stats()


@router.get("/tree", response_model=CorpusTreeResponse, summary="Full corpus topic tree")
async def corpus_tree(
    enrollment_year: int | None = Query(None, alias="enrollmentYear", ge=0, le=9999),
    academic_year: int | None = Query(None, alias="academicYear", ge=0, le=9999),
    lecturer_only: bool | None = Query(None, alias="lecturerOnly"),
    _admin: JWTPayload = Depends(require_admin),
):
    metadata_filter = {}
    if enrollment_year is not None:
        metadata_filter["enrollment_year"] = {
            "from_year": enrollment_year,
            "to_year": enrollment_year,
        }
    if academic_year is not None:
        metadata_filter["academic_year"] = {
            "from_year": academic_year,
            "to_year": academic_year,
        }
    return await get_corpus_service().build_tree(
        metadata_filter=metadata_filter or None,
        lecturer_only=lecturer_only,
    )


@router.get("/topics", response_model=CorpusNodeListResponse, summary="List corpus topics")
async def list_topics(_admin: JWTPayload = Depends(require_admin)):
    return await get_corpus_service().list_topics()


@router.get("/topics/{topicKey:path}", response_model=CorpusNodeResponse, summary="Get a corpus topic")
async def get_topic(
    node_key: str = Path(..., alias="topicKey"),
    _admin: JWTPayload = Depends(require_admin),
):
    try:
        return await get_corpus_service().get_topic(node_key)
    except ValueError as exc:
        raise _http_error(exc) from exc


@router.get("/files/{fileId}/topics", response_model=CorpusPayloadTopicsResponse, summary="Get Corpus topics assigned to a file")
async def get_file_topics(
    file_id: str = Path(..., alias="fileId"),
    _admin: JWTPayload = Depends(require_admin),
):
    try:
        return await get_corpus_service().get_payload_topics("file", file_id)
    except ValueError as exc:
        raise _http_error(exc) from exc


@router.put("/files/{fileId}/topics", response_model=CorpusPayloadTopicsResponse, summary="Replace Corpus topic assignments for a file")
async def update_file_topics(
    body: PayloadTopicsUpdateRequest,
    file_id: str = Path(..., alias="fileId"),
    _admin: JWTPayload = Depends(require_admin),
):
    try:
        return await get_corpus_service().update_payload_topics("file", file_id, body.node_keys)
    except ValueError as exc:
        raise _http_error(exc) from exc


@router.get("/faqs/{faqId}/topics", response_model=CorpusPayloadTopicsResponse, summary="Get Corpus topics assigned to an FAQ")
async def get_faq_topics(
    faq_id: str = Path(..., alias="faqId"),
    _admin: JWTPayload = Depends(require_admin),
):
    try:
        return await get_corpus_service().get_payload_topics("faq", faq_id)
    except ValueError as exc:
        raise _http_error(exc) from exc


@router.put("/faqs/{faqId}/topics", response_model=CorpusPayloadTopicsResponse, summary="Replace Corpus topic assignments for an FAQ")
async def update_faq_topics(
    body: PayloadTopicsUpdateRequest,
    faq_id: str = Path(..., alias="faqId"),
    _admin: JWTPayload = Depends(require_admin),
):
    try:
        return await get_corpus_service().update_payload_topics("faq", faq_id, body.node_keys)
    except ValueError as exc:
        raise _http_error(exc) from exc


@router.post("/topics", response_model=CorpusNodeResponse, status_code=201, summary="Create a corpus topic")
async def create_topic(
    body: TopicCreateRequest,
    _admin: JWTPayload = Depends(require_admin),
):
    try:
        return await get_corpus_service().create_topic(body)
    except ValueError as exc:
        raise _http_error(exc) from exc


@router.patch("/topics/{topicKey:path}", response_model=CorpusNodeResponse, summary="Update a corpus topic")
async def update_topic(
    body: TopicUpdateRequest,
    node_key: str = Path(..., alias="topicKey"),
    _admin: JWTPayload = Depends(require_admin),
):
    try:
        return await get_corpus_service().update_topic(node_key, body)
    except ValueError as exc:
        raise _http_error(exc) from exc


@router.post("/topics/{sourceKey:path}/merge", response_model=TopicMergeResponse, summary="Merge a corpus topic")
async def merge_topic(
    body: TopicMergeRequest,
    source_node_key: str = Path(..., alias="sourceKey"),
    _admin: JWTPayload = Depends(require_admin),
):
    try:
        return await get_corpus_service().merge_topics(source_node_key, body.target_key)
    except ValueError as exc:
        raise _http_error(exc) from exc


@router.delete("/topics/{topicKey:path}", response_model=TopicDeleteResponse, summary="Delete a corpus topic")
async def delete_topic(
    node_key: str = Path(..., alias="topicKey"),
    _admin: JWTPayload = Depends(require_admin),
):
    try:
        return await get_corpus_service().delete_topic(node_key)
    except ValueError as exc:
        raise _http_error(exc) from exc


@router.post("/backfill", response_model=BackfillStartResponse, summary="Trigger corpus backfill")
async def trigger_backfill(_admin: JWTPayload = Depends(require_admin)):
    return await get_corpus_job_service().trigger_backfill()
