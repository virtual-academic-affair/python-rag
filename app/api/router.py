"""
Main API Router - Aggregates all endpoint routers.
Unified router combining email classification and RAG features.
"""

from fastapi import APIRouter
import logging

logger = logging.getLogger(__name__)

api_router = APIRouter()


# ====================================
# ROOT
# ====================================

@api_router.get("/", tags=["Health"])
async def root():
    """Root endpoint."""
    return {"message": "AI Service is running"}


# ====================================
# CLASSIFICATION ENDPOINTS
# ====================================

from app.api.endpoints import classification

api_router.include_router(classification.router)
logger.info("✅ Classification routes included")


# ====================================
# RAG ENDPOINTS
# ====================================

from app.api.endpoints import chat, files, stores, metadata, file_progress_ws

api_router.include_router(chat.router, prefix="/api", tags=["Chat"])
api_router.include_router(files.router, prefix="/api", tags=["Files"])
api_router.include_router(stores.router, prefix="/api", tags=["Stores"])
api_router.include_router(metadata.router, prefix="/api", tags=["Metadata"])
api_router.include_router(file_progress_ws.router, prefix="/api", tags=["Files"])
logger.info("✅ RAG endpoints included (chat, files, stores, metadata, file_progress_ws)")
