from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status

from app.core.auth import JWTPayload
from app.core.dependencies import require_admin
from app.modules.corpus.dtos import (
    BackfillStartResponse,
    CorpusTopicListResponse,
    CorpusTopicDetailResponse,
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
from app.modules.metadata.dtos import UnifiedFilterSchema

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
    metadata_filter: str | None = Query(None, alias="metadataFilter", description="JSON metadata filter"),
    lecturer_only: bool | None = Query(None, alias="lecturerOnly"),
    _admin: JWTPayload = Depends(require_admin),
):
    parsed_filter = None
    if metadata_filter:
        try:
            raw_filter = json.loads(metadata_filter)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid metadataFilter JSON") from exc
        try:
            parsed_filter = UnifiedFilterSchema.model_validate(raw_filter).model_dump(
                by_alias=False,
                exclude_none=True,
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid metadataFilter: {exc}") from exc
    return await get_corpus_service().build_tree(
        metadata_filter=parsed_filter,
        lecturer_only=lecturer_only,
    )


@router.get("/topics", response_model=CorpusTopicListResponse, summary="List corpus topics")
async def list_topics(_admin: JWTPayload = Depends(require_admin)):
    return await get_corpus_service().list_topics()


@router.get("/topics/{topicKey:path}", response_model=CorpusTopicDetailResponse, summary="Get a corpus topic")
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


@router.post("/topics", response_model=CorpusTopicDetailResponse, status_code=201, summary="Create a corpus topic")
async def create_topic(
    body: TopicCreateRequest,
    _admin: JWTPayload = Depends(require_admin),
):
    try:
        return await get_corpus_service().create_topic(body)
    except ValueError as exc:
        raise _http_error(exc) from exc


@router.patch("/topics/{topicKey:path}", response_model=CorpusTopicDetailResponse, summary="Update a corpus topic")
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
