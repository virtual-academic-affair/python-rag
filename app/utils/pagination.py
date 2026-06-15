"""
Pagination utilities.
Provides pagination helpers for API responses.
"""

from typing import List, Dict, Any, Optional
from pydantic import Field
from app.core.base_schema import BaseSchema


class PaginationParams(BaseSchema):
    """Pagination query parameters."""
    page: int = Field(default=1, ge=1, description="Page number (1-indexed)")
    limit: int = Field(default=20, ge=1, le=100, description="Items per page")
    
    @property
    def skip(self) -> int:
        """Calculate number of items to skip."""
        return (self.page - 1) * self.limit


class PaginatedResponse(BaseSchema):
    """Paginated API response wrapper."""
    items: List[Any] = Field(..., description="List of items")
    total: int = Field(..., description="Total number of items")
    page: int = Field(..., description="Current page number")
    limit: int = Field(..., description="Items per page")
    total_pages: int = Field(..., description="Total number of pages")
    has_next: bool = Field(..., description="Whether there is a next page")
    has_prev: bool = Field(..., description="Whether there is a previous page")
    
    @classmethod
    def create(
        cls,
        items: List[Any],
        total: int,
        page: int,
        limit: int,
    ) -> "PaginatedResponse":
        """
        Create paginated response.
        
        Args:
            items: List of items for current page
            total: Total number of items
            page: Current page number
            limit: Items per page
            
        Returns:
            PaginatedResponse instance
        """
        total_pages = (total + limit - 1) // limit  # Ceiling division
        
        return cls(
            items=items,
            total=total,
            page=page,
            limit=limit,
            total_pages=total_pages,
            has_next=page < total_pages,
            has_prev=page > 1,
        )


def paginate_query_results(
    items: List[Any],
    total: int,
    params: PaginationParams,
) -> PaginatedResponse:
    """
    Helper function to create paginated response.
    
    Args:
        items: Query results
        total: Total count
        params: Pagination parameters
        
    Returns:
        PaginatedResponse
    """
    return PaginatedResponse.create(
        items=items,
        total=total,
        page=params.page,
        limit=params.limit,
    )
