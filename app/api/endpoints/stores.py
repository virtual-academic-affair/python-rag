"""
Store Management Endpoints - Handle Gemini File Search store operations.
Provides CRUD operations for managing stores and synchronizing with Gemini API.
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query
import logging
from typing import Dict, Any

from app.models.schemas import (
    CreateStoreRequest,
    UpdateStoreRequest,
    StoreDetailResponse,
    StoreListResponse,
    BulkDeleteResponse,
)
from app.services.rag.store_service import get_store_service
from app.core.exceptions import (
    GeminiException,
    ValidationException,
    ConflictException,
    NotFoundException,
)
from app.dependencies.auth import require_admin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/stores", tags=["Stores"])


def _to_store_response(store) -> StoreDetailResponse:
    """Helper function to convert StoreDocument to StoreDetailResponse."""
    return StoreDetailResponse(
        store_id=str(store.id),
        store_name=store.store_name,
        display_name=store.display_name,
        file_count=store.file_count,
        total_size=store.total_size,
        is_default=store.is_default,
        created_at=store.created_at.isoformat() if store.created_at else None,
        updated_at=store.updated_at.isoformat() if store.updated_at else None,
    )


@router.post(
    "",
    response_model=StoreDetailResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create store",
    description="Create a new Gemini File Search store.",
)
async def create_store(request: CreateStoreRequest, _admin: Dict[str, Any] = Depends(require_admin)):
    """
    Create a new Gemini File Search store.
    
    **Example:**
    ```json
    {
      "display_name": "Đào tạo 2026",
      "set_as_default": false
    }
    ```
    """
    try:
        store_svc = get_store_service()
        store = await store_svc.create_store(
            display_name=request.display_name,
            set_as_default=request.set_as_default,
        )
        
        return _to_store_response(store)
        
    except ConflictException as e:
        logger.warning(f"Duplicate store: {e}")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        )
    
    except GeminiException as e:
        logger.error(f"Gemini error creating store: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )
    
    except Exception as e:
        logger.error(f"Error creating store: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create store: {str(e)}",
        )


@router.get(
    "",
    response_model=StoreListResponse,
    summary="List stores",
    description="List all stores with pagination. Use is_default=true to get default store.",
)
async def list_stores(
    is_default: bool = Query(None, description="Filter by default store (true to get default store only)"),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(50, ge=1, le=100, description="Items per page"),
    _admin: Dict[str, Any] = Depends(require_admin),
):
    """
    List stores with pagination.
    
    **Query params:**
    - `is_default=true`: Get only the default store
    - `page`, `limit`: Pagination
    """
    try:
        store_svc = get_store_service()
        
        # If requesting default store only
        if is_default is True:
            default_store = await store_svc.get_default_store()
            if not default_store:
                return StoreListResponse(
                    stores=[],
                    total=0,
                    page=1,
                    limit=limit,
                )
            return StoreListResponse(
                stores=[_to_store_response(default_store)],
                total=1,
                page=1,
                limit=limit,
            )
        
        skip = (page - 1) * limit
        stores, total = await store_svc.list_stores(
            skip=skip,
            limit=limit,
        )
        
        store_responses = [_to_store_response(s) for s in stores]
        
        return StoreListResponse(
            stores=store_responses,
            total=total,
            page=page,
            limit=limit,
        )
        
    except Exception as e:
        logger.error(f"Error listing stores: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list stores: {str(e)}",
        )


@router.get(
    "/{store_id}",
    response_model=StoreDetailResponse,
    summary="Get store details",
    description="Get detailed information about a specific store.",
)
async def get_store(store_id: str, _admin: Dict[str, Any] = Depends(require_admin)):
    """
    Get store details by ID.
    """
    try:
        store_svc = get_store_service()
        store = await store_svc.get_store(store_id)
        if not store:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Store {store_id} not found",
            )
        
        return _to_store_response(store)
        
    except Exception as e:
        logger.error(f"Error getting store {store_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get store: {str(e)}",
        )


@router.patch(
    "/{store_id}",
    response_model=StoreDetailResponse,
    summary="Update store",
    description="Update store properties.",
)
async def update_store(store_id: str, request: UpdateStoreRequest, _admin: Dict[str, Any] = Depends(require_admin)):
    """
    Update store properties.
    """
    try:
        store_svc = get_store_service()
        store = await store_svc.update_store(
            store_id=store_id,
            display_name=request.display_name,
            is_default=request.is_default,
        )
        
        return _to_store_response(store)
        
    except NotFoundException as e:
        logger.warning(f"Store not found: {e}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    
    except Exception as e:
        logger.error(f"Error updating store {store_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update store: {str(e)}",
        )

@router.delete(
    "/all",
    response_model=BulkDeleteResponse,
    summary="Delete all stores",
    description="Delete all stores (from Gemini, R2, and MongoDB).",
)
async def delete_all_stores():
    """
    Delete all stores (full delete from Gemini, R2, and MongoDB).
    
    **Warning:** This will permanently delete all stores and their files!
    """
    try:
        store_svc = get_store_service()
        deleted_count = await store_svc.delete_all_stores()
        
        return BulkDeleteResponse(
            deleted_count=deleted_count,
            message=f"Deleted {deleted_count} stores (full delete)",
        )
        
    except GeminiException as e:
        logger.error(f"Gemini error deleting all stores: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )
    
    except Exception as e:
        logger.error(f"Error deleting all stores: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete all stores: {str(e)}",
        )


@router.delete(
    "/{store_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete store",
    description="Delete a store (hard delete).",
)
async def delete_store(
    store_id: str,
    force: bool = Query(False, description="Force delete even if files exist"),
    _admin: Dict[str, Any] = Depends(require_admin),
):
    """
    Delete a store (hard delete).
    
    **Deletion Behavior:**
    - force=false: Prevent deletion if files exist
    - force=true: Delete store and all files
    """
    try:
        store_svc = get_store_service()
        await store_svc.delete_store(store_id, force=force)
        return None
        
    except NotFoundException as e:
        logger.warning(f"Store not found: {e}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    
    except ValidationException as e:
        logger.warning(f"Validation error: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    
    except GeminiException as e:
        logger.error(f"Gemini error deleting store: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )
    
    except Exception as e:
        logger.error(f"Error deleting store {store_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete store: {str(e)}",
        )


@router.post(
    "/{store_id}/sync",
    response_model=StoreDetailResponse,
    summary="Sync store stats",
    description="Synchronize store statistics with Gemini API.",
)
async def sync_store_stats(store_id: str, _admin: Dict[str, Any] = Depends(require_admin)):
    """
    Sync store statistics with Gemini API.
    Updates file_count and total_size from Gemini.
    """
    try:
        store_svc = get_store_service()
        store = await store_svc.sync_store_stats(store_id)
        
        return _to_store_response(store)
        
    except NotFoundException as e:
        logger.warning(f"Store not found: {e}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    
    except GeminiException as e:
        logger.error(f"Gemini sync failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )
    
    except Exception as e:
        logger.error(f"Error syncing store {store_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to sync store: {str(e)}",
        )
