"""Service for handling administrative requests"""
import logging
from app.models.schemas import InternalData, AdministrativeResponse

logger = logging.getLogger(__name__)


class AdministrativeService:
    """Service for processing administrative requests"""
    
    async def process(
        self,
        internal_data: InternalData,
        title: str,
        content: str
    ) -> AdministrativeResponse:
        """Process administrative request and return response."""
        logger.info("Processing administrative request")
        return AdministrativeResponse(
            internal=internal_data,
            types=["administrative"]
        )

