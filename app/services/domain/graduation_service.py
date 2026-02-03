"""Service for handling graduation requests"""
import logging
from app.models.schemas import InternalData, GraduationResponse

logger = logging.getLogger(__name__)


class GraduationService:
    """Service for processing graduation requests"""

    async def process(
        self, internal_data: InternalData, title: str, content: str
    ) -> GraduationResponse:
        """Process graduation request and return response."""
        logger.info("Processing graduation request")
        return GraduationResponse(internal=internal_data, types=["graduation"])
