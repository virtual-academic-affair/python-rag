from fastapi import APIRouter, Depends
from typing import Dict, Any

from app.modules.metadata.dtos import MetadataSchemaResponse
from app.modules.metadata.services.metadata_service import get_metadata_service
from app.core.dependencies import require_auth

router = APIRouter(prefix="/metadata", tags=["Metadata"])

@router.get(
    "/schema",
    response_model=MetadataSchemaResponse,
    summary="Get metadata schema",
    description=(
        "Returns the fixed metadata schema definition — document types and sentinel values — "
        "so the frontend can render the file-upload / FAQ-import forms correctly."
    ),
)
async def get_metadata_schema(
    _user: Dict[str, Any] = Depends(require_auth),
):
    """Return the static metadata schema (no DB access)."""
    validator = get_metadata_service()
    schema_def = validator.get_schema_definition()
    return MetadataSchemaResponse(
        document_types=[d["value"] for d in schema_def["documentTypes"]],
        year_min=schema_def["yearMin"],
        year_max=schema_def["yearMax"],
    )
