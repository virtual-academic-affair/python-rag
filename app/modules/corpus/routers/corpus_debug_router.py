from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.auth import JWTPayload
from app.core.dependencies import require_admin
from app.modules.corpus.dtos import (
    ChatPreviewRequest,
    ChatPreviewResponse,
    TraverseRequest,
    TraverseResponse,
)
from app.modules.corpus.services.corpus_debug_service import get_corpus_debug_service

router = APIRouter(prefix="/debug/corpus", tags=["Debug Corpus"])


@router.post("/traverse", response_model=TraverseResponse, summary="Dry-run corpus traversal")
async def debug_traverse(
    body: TraverseRequest,
    _admin: JWTPayload = Depends(require_admin),
):
    return await get_corpus_debug_service().traverse(body)


@router.post(
    "/chat-preview",
    response_model=ChatPreviewResponse,
    summary="Dry-run the shared chat RAG pipeline without a real JWT",
)
async def debug_chat_preview(
    body: ChatPreviewRequest,
    _admin: JWTPayload = Depends(require_admin),
):
    return await get_corpus_debug_service().chat_preview(body)
