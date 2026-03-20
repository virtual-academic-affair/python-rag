"""
Metadata Type Management Endpoints - Phase 4 refactored.
CRUD operations for metadata field definitions with AllowedValue support.
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query, Path
import logging
from typing import Dict, Any

from app.models.schemas import (
    CreateMetadataTypeRequest,
    UpdateMetadataTypeRequest,
    MetadataTypeResponse,
    MetadataTypeListResponse,
    AllowedValueSchema,
    AllowedValueResponse,
)
from app.models.database import AllowedValue
from app.services.rag.metadata_service import get_metadata_service
from app.core.exceptions import (
    ValidationException,
    ConflictException,
    NotFoundException,
    ForbiddenException,
)
from app.dependencies.auth import require_admin, require_auth

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/metadata", tags=["Metadata"])


def _convert_allowed_values_to_schema(allowed_values_list) -> list[AllowedValueSchema] | None:
    """Convert AllowedValue objects to API schema."""
    if allowed_values_list is None:
        return None
    return [
        AllowedValueSchema(
            value=av.value,
            display_name=av.display_name,
            is_active=av.is_active,
            color=av.color,
            total_files=av.total_files,
        )
        for av in allowed_values_list
    ]


def _convert_schema_to_allowed_values(schemas: list[AllowedValueSchema] | None) -> list[AllowedValue] | None:
    """Convert API schemas to AllowedValue objects."""
    if schemas is None:
        return None
    return [
        AllowedValue(
            value=s.value,
            display_name=s.display_name,
            is_active=s.is_active,
            color=s.color,
        )
        for s in schemas
    ]


@router.post(
    "",
    response_model=MetadataTypeResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create metadata type",
    description="Create a new metadata field type definition.",
)
async def create_metadata_type(request: CreateMetadataTypeRequest, _admin: Dict[str, Any] = Depends(require_admin)):
    """
    Create a new metadata type definition.
    
    **Example:**
    ```json
    {
      "key": "department",
      "displayName": "Phòng ban",
      "description": "Phòng ban quản lý tài liệu",
      "allowedValues": [
        {"value": "dao_tao", "displayName": "Đào tạo", "isActive": true, "color": "#3498DB"},
        {"value": "khcn", "displayName": "KHCN", "isActive": true}
      ],
      "supportAllValue": false
    }
    ```
    """
    try:
        metadata_svc = get_metadata_service()
        
        # Convert schemas to AllowedValue objects
        allowed_values = _convert_schema_to_allowed_values(request.allowed_values)
        
        metadata_type = await metadata_svc.create_metadata_type(
            key=request.key,
            display_name=request.display_name,
            description=request.description,
            allowed_values=allowed_values,
        )
        
        return MetadataTypeResponse(
            metadata_id=str(metadata_type.id),
            key=metadata_type.key,
            display_name=metadata_type.display_name,
            description=metadata_type.description,
            allowed_values=_convert_allowed_values_to_schema(metadata_type.get_allowed_values()),
            is_active=metadata_type.is_active,
            is_system=metadata_type.is_system,
            total_files=metadata_type.total_files,
            created_at=metadata_type.created_at.isoformat() if metadata_type.created_at else None,
            updated_at=metadata_type.updated_at.isoformat() if metadata_type.updated_at else None,
        )
        
    except ConflictException as e:
        logger.warning(f"Duplicate metadata key: {e}")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        )
    
    except ValidationException as e:
        logger.warning(f"Validation error: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    
    except Exception as e:
        logger.error(f"Error creating metadata type: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create metadata type: {str(e)}",
        )


@router.get(
    "",
    response_model=MetadataTypeListResponse,
    summary="List metadata types",
    description="List all metadata type definitions with optional active filter (Phase 4).",
)
async def list_metadata_types(
    active_only: bool = Query(False, description="If true, only return is_active=true types"),
    _user: Dict[str, Any] = Depends(require_auth)
):
    """
    List all metadata type definitions.
    
    **Phase 4:** Supports `active_only` query param to filter by is_active status.
    """
    try:
        metadata_svc = get_metadata_service()
        metadata_types = await metadata_svc.list_all_metadata_types(active_only=active_only)
        
        type_responses = [
            MetadataTypeResponse(
                metadata_id=str(mt.id),
                key=mt.key,
                display_name=mt.display_name,
                description=mt.description,
                allowed_values=_convert_allowed_values_to_schema(mt.get_allowed_values()),
                is_active=mt.is_active,
                is_system=mt.is_system,
                total_files=mt.total_files,
                created_at=mt.created_at.isoformat() if mt.created_at else None,
                updated_at=mt.updated_at.isoformat() if mt.updated_at else None,
            )
            for mt in metadata_types
        ]
        
        return MetadataTypeListResponse(
            metadata_types=type_responses,
            total=len(type_responses),
        )
        
    except Exception as e:
        logger.error(f"Error listing metadata types: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list metadata types: {str(e)}",
        )


@router.get(
    "/{key}",
    response_model=MetadataTypeResponse,
    summary="Get metadata type",
    description="Get a specific metadata type by key (Phase 4).",
)
async def get_metadata_type(
    key: str,
    _user: Dict[str, Any] = Depends(require_auth)
):
    """
    Get metadata type details by key.
    """
    try:
        metadata_svc = get_metadata_service()
        metadata_type = await metadata_svc.get_metadata_type(key)
        if not metadata_type:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Metadata type '{key}' not found",
            )
        
        return MetadataTypeResponse(
            metadata_id=str(metadata_type.id),
            key=metadata_type.key,
            display_name=metadata_type.display_name,
            description=metadata_type.description,
            allowed_values=_convert_allowed_values_to_schema(metadata_type.get_allowed_values()),
            is_active=metadata_type.is_active,
            is_system=metadata_type.is_system,
            total_files=metadata_type.total_files,
            created_at=metadata_type.created_at.isoformat() if metadata_type.created_at else None,
            updated_at=metadata_type.updated_at.isoformat() if metadata_type.updated_at else None,
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting metadata type {key}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get metadata type: {str(e)}",
        )


@router.patch(
    "/{key}",
    response_model=MetadataTypeResponse,
    summary="Update metadata type",
    description="Update an existing metadata type definition (Phase 4). Cannot update key or is_system.",
)
async def update_metadata_type(key: str, request: UpdateMetadataTypeRequest, _admin: Dict[str, Any] = Depends(require_admin)):
    """
    Update metadata type properties.
    
    **Phase 4:** Cannot update key (immutable) or is_system (set at creation).
    """
    try:
        metadata_svc = get_metadata_service()
        
        # Convert schemas to AllowedValue objects
        allowed_values = _convert_schema_to_allowed_values(request.allowed_values)
        
        metadata_type = await metadata_svc.update_metadata_type(
            key=key,
            display_name=request.display_name,
            description=request.description,
            allowed_values=allowed_values,
            is_active=request.is_active,
        )
        
        return MetadataTypeResponse(
            metadata_id=str(metadata_type.id),
            key=metadata_type.key,
            display_name=metadata_type.display_name,
            description=metadata_type.description,
            allowed_values=_convert_allowed_values_to_schema(metadata_type.get_allowed_values()),
            is_active=metadata_type.is_active,
            is_system=metadata_type.is_system,
            total_files=metadata_type.total_files,
            created_at=metadata_type.created_at.isoformat() if metadata_type.created_at else None,
            updated_at=metadata_type.updated_at.isoformat() if metadata_type.updated_at else None,
        )
        
    except NotFoundException as e:
        logger.warning(f"Metadata type not found: {e}")
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
    
    except Exception as e:
        logger.error(f"Error updating metadata type {key}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update metadata type: {str(e)}",
        )


@router.delete(
    "/{key}/values/{value}",
    response_model=MetadataTypeResponse,
    summary="Delete a specific value from metadata type",
    description="Hard deletes a value from allowed_values if its total_files is 0. If it has active files, returns 409 Conflict.",
)
async def delete_metadata_value(
    key: str = Path(..., description="The unique key of the metadata type"),
    value: str = Path(..., description="The value to delete from allowed_values"),
    _admin: Dict[str, Any] = Depends(require_admin),
):
    """
    Hard-delete a metadata value.
    Can only be deleted if total_files for this value is 0.
    """
    metadata_svc = get_metadata_service()
    try:
        updated_metadata = await metadata_svc.delete_metadata_value(key, value)
        
        # Convert to response
        allowed_values = None
        if updated_metadata.allowed_values:
            allowed_values = [
                AllowedValueResponse(
                    value=av["value"],
                    display_name=av.get("display_name", av["value"]),
                    is_active=av.get("is_active", True),
                    color=av.get("color"),
                    total_files=av.get("total_files", 0)
                ) for av in updated_metadata.allowed_values
            ]
            
        return MetadataTypeResponse(
            metadata_id=str(updated_metadata.id),
            key=updated_metadata.key,
            display_name=updated_metadata.display_name,
            description=updated_metadata.description,
            allowed_values=allowed_values,
            is_active=updated_metadata.is_active,
            is_system=updated_metadata.is_system,
            total_files=updated_metadata.total_files,
            created_at=updated_metadata.created_at.isoformat() if updated_metadata.created_at else "",
            updated_at=updated_metadata.updated_at.isoformat() if updated_metadata.updated_at else ""
        )

    except NotFoundException as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    except ConflictException as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Error deleting metadata value {value} from {key}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete metadata value: {str(e)}",
        )


@router.delete(
    "/{key}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete metadata type",
    description="Hard-delete a metadata type. Cannot delete system metadata types.",
)
async def delete_metadata_type(key: str, _admin: Dict[str, Any] = Depends(require_admin)):
    metadata_svc = get_metadata_service()

    try:
        await metadata_svc.delete_metadata_type(key)
        return None

    except ForbiddenException as e:
        logger.warning(f"Forbidden: cannot delete system metadata: {e}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e),
        )

    except ConflictException as e:
        logger.warning(f"Conflict: cannot delete metadata type in use: {e}")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        )

    except NotFoundException as e:
        logger.warning(f"Metadata type not found: {e}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )

    except Exception as e:
        logger.error(f"Error deleting metadata type {key}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete metadata type: {str(e)}",
        )
