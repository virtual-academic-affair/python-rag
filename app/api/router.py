"""
Main API Router - Aggregates all endpoint routers.
Unified router combining email classification and RAG features.
"""

from fastapi import APIRouter
import logging
from app.modules.email.router import router as email_router
from app.modules.chat.router import router as chat_router
from app.modules.files.router import router as files_router
from app.modules.files.ws import router as files_ws
from app.modules.metadata.router import router as metadata_router
from app.modules.files.debug_router import router as debug_router
from app.modules.files.toc_tree.router import router as toc_tree_router

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
api_router.include_router(chat_router, prefix="/api")
api_router.include_router(files_router, prefix="/api")
api_router.include_router(metadata_router, prefix="/api")
api_router.include_router(files_ws, prefix="/api")
api_router.include_router(debug_router, prefix="/api")
api_router.include_router(toc_tree_router, prefix="/api")

logger.info("✅ All modular routers included (email, chat, files, metadata)")
