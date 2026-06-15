from fastapi import APIRouter, Depends, HTTPException, status
from typing import Dict, Any
import logging

from app.core.dependencies import require_auth
from app.core.exceptions import NotFoundException
from app.modules.files.toc_tree.services.toc_tree_service import get_toc_tree_service
from app.modules.files.toc_tree.dtos import TocTreeResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/toc-tree", tags=["TOC Tree"])

@router.get(
    "/{file_id}",
    response_model=TocTreeResponse,
    summary="Get Table of Contents for a file",
    description="Retrieve the hierarchical Table of Contents (TOC) structure for a given file_id.",
)
async def get_toc_tree(
    file_id: str,
    _user: Dict[str, Any] = Depends(require_auth)
):
    try:
        svc = get_toc_tree_service()
        toc_data = await svc.get_toc_tree(file_id)
        return TocTreeResponse(**toc_data)
    except NotFoundException as e:
        logger.warning(f"TOC not found for {file_id}")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to fetch TOC tree for {file_id}: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal server error")
