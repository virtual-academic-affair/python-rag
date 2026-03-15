"""
Store Utility Functions.
Helper functions for resolving store across the application.
"""

from typing import Optional, Tuple
from fastapi import HTTPException, status
from bson import ObjectId
from bson.errors import InvalidId

from app.repositories.store_repository import StoreRepository



async def resolve_store(request_store_id: Optional[str] = None) -> Tuple[str, str]:
    """
    Resolve store by priority and return both store_id and store_name.
    
    Priority:
    1. If request has store_id, look up store_name from database
    2. Get default store from database (is_default=True)
    3. Raise error if no store available
    
    Args:
        request_store_id: store_id from API request (optional)
        
    Returns:
        Tuple of (store_id, store_name)
        
    Raises:
        HTTPException: If store not found or no store available
    """
    store_repo = StoreRepository()

    # 1. Use request store_id if provided
    if request_store_id:
        try:
            ObjectId(request_store_id)  # validate format
        except (InvalidId, Exception):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid store_id format: {request_store_id}",
            )

        store = await store_repo.find_by_id(request_store_id)
        if not store:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Store not found: {request_store_id}",
            )

        return store["_id"], store["store_name"]

    # 2. Get default store from database
    default_store = await store_repo.find_default_store()
    if default_store and default_store.get("store_name"):
        return default_store["_id"], default_store["store_name"]

    # 3. No store available - raise error
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="No store available. Please create a store first or provide store_id in request.",
    )


async def get_store_name_by_id(store_id: str) -> str:
    """
    Get store_name (Gemini name) from store_id.
    
    Args:
        store_id: MongoDB ObjectId as string
        
    Returns:
        Gemini store name (fileSearchStores/xxx)
        
    Raises:
        HTTPException: If store not found
    """
    store_repo = StoreRepository()

    try:
        ObjectId(store_id)  # validate format
    except (InvalidId, Exception):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid store_id format: {store_id}",
        )

    store = await store_repo.find_by_id(store_id)
    if not store:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Store not found: {store_id}",
        )

    return store["store_name"]
