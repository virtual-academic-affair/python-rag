from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.auth import JWTPayload
from app.core.dependencies import require_admin
from app.modules.corpus.dtos import (
    CorpusTraversalRequest,
    CorpusTraversalResponse,
)
from app.modules.corpus.services.corpus_debug_service import get_corpus_debug_service
from app.modules.rag.query.debug_service import get_rag_debug_service
from app.modules.rag.query.dtos import RagChatPreviewRequest, RagChatPreviewResponse

router = APIRouter(prefix="/debug/corpus", tags=["Debug Corpus"])


@router.post("/traverse", response_model=CorpusTraversalResponse, summary="Dry-run corpus traversal")
async def debug_traverse(
    body: CorpusTraversalRequest,
    _admin: JWTPayload = Depends(require_admin),
):
    return await get_corpus_debug_service().traverse(body)


@router.post(
    "/chat-preview",
    response_model=RagChatPreviewResponse,
    summary="Dry-run the shared chat RAG pipeline without a real JWT",
)
async def debug_chat_preview(
    body: RagChatPreviewRequest,
    _admin: JWTPayload = Depends(require_admin),
):
    return await get_rag_debug_service().chat_preview(body)
