"""Service for handling other requests"""
import logging
from app.models.schemas import InternalData, OtherResponse

logger = logging.getLogger(__name__)


class OtherService:
    """Service for processing other requests"""
    
    async def process(
        self,
        internal_data: InternalData,
        title: str,
        content: str
    ) -> OtherResponse:
        """Process other request and return response."""
        logger.info("Processing other request")
        return OtherResponse(
            internal=internal_data,
            types=["other"]
        )

