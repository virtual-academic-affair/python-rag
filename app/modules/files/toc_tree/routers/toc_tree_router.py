from fastapi import APIRouter, Depends

from app.core.auth import JWTPayload
from app.core.dependencies import require_auth
from app.modules.files.toc_tree.services.toc_tree_service import get_toc_tree_service
from app.modules.files.toc_tree.dtos import TocTreeResponse

router = APIRouter(prefix="/toc-tree", tags=["TOC Tree"])

@router.get(
    "/{file_id}",
    response_model=TocTreeResponse,
    summary="Get Table of Contents for a file",
    description="Retrieve the hierarchical Table of Contents (TOC) structure for a given file_id.",
)
async def get_toc_tree(
    file_id: str,
    _user: JWTPayload = Depends(require_auth)
):
    svc = get_toc_tree_service()
    toc_data = await svc.get_toc_tree(file_id)
    return TocTreeResponse.from_model(toc_data)
