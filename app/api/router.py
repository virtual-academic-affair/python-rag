"""
Main API Router - Aggregates all endpoint routers.
Unified router combining email classification and RAG features.
"""

from fastapi import APIRouter
import logging
from app.modules.email import router as email_router
from app.modules.email import ws_router as email_ws
from app.modules.chat.routers.chat_router import router as chat_router
from app.modules.files.routers.file_router import router as files_router
from app.modules.files.routers.file_ws_router import router as files_ws
from app.modules.metadata.routers.metadata_router import router as metadata_router
from app.modules.files.routers.debug_router import router as debug_router
from app.modules.files.toc_tree.routers.toc_tree_router import router as toc_tree_router
from app.modules.faq.routers.faq_router import router as faq_router
from app.modules.forms import router as forms_router
from app.modules.corpus.routers.corpus_router import router as corpus_router
from app.modules.corpus.routers.corpus_debug_router import router as corpus_debug_router

logger = logging.getLogger(__name__)

api_router = APIRouter()


# ====================================
# ROOT
# ====================================

@api_router.get("/", tags=["Health"])
async def root():
    """Root endpoint."""
    return {"message": "AI Service is running"}


# Registration
api_router.include_router(email_router, prefix="/api")
api_router.include_router(email_ws, prefix="/api")
api_router.include_router(chat_router, prefix="/api")
api_router.include_router(files_router, prefix="/api")
api_router.include_router(metadata_router, prefix="/api")
api_router.include_router(files_ws, prefix="/api")
api_router.include_router(debug_router, prefix="/api")
api_router.include_router(toc_tree_router, prefix="/api")
api_router.include_router(faq_router, prefix="/api")
api_router.include_router(forms_router, prefix="/api")
api_router.include_router(corpus_router, prefix="/api")
api_router.include_router(corpus_debug_router, prefix="/api")

logger.info("✅ All modular routers included (email, chat, files, metadata, forms)")
