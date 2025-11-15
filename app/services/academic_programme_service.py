"""Service for handling academic programme requests"""
import logging
from app.models.schemas import InternalData, AcademicProgrammeResponse

logger = logging.getLogger(__name__)


class AcademicProgrammeService:
    """Service for processing academic programme requests"""
    
    async def process(
        self,
        internal_data: InternalData,
        title: str,
        content: str
    ) -> AcademicProgrammeResponse:
        """Process academic programme request and return response."""
        logger.info("Processing academic programme request")
        return AcademicProgrammeResponse(
            internal=internal_data,
            types=["academic_programme"]
        )

