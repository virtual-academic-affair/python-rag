"""Service for handling department requests"""
import logging
from app.models.schemas import InternalData, DepartmentResponse

logger = logging.getLogger(__name__)


class DepartmentService:
    """Service for processing department requests"""
    
    async def process(
        self,
        internal_data: InternalData,
        title: str,
        content: str
    ) -> DepartmentResponse:
        """Process department request and return response."""
        logger.info("Processing department request")
        return DepartmentResponse(
            internal=internal_data,
            types=["department"]
        )

