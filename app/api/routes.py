"""API routes definitions"""
import logging
from fastapi import APIRouter, HTTPException, Depends
from app.models.schemas import RequestData, ProcessResponse
from app.services.langchain_service import LangChainClassifier

logger = logging.getLogger(__name__)

router = APIRouter()


def get_classifier() -> LangChainClassifier:
    """Dependency to get the classifier instance."""
    from app.main import classifier
    if classifier is None:
        raise HTTPException(status_code=500, detail="Classifier not initialized")
    return classifier


@router.get("/")
async def root():
    """Health check endpoint."""
    return {"message": "Student Classification Service is running"}


@router.get("/health")
async def health_check():
    """Detailed health check."""
    from app.main import classifier
    return {
        "status": "healthy",
        "service": "Student Classification Service",
        "classifier_ready": classifier is not None
    }


@router.post("/process", response_model=ProcessResponse)
async def process_request(
    request: RequestData,
    classifier_service: LangChainClassifier = Depends(get_classifier)
):
    """
    Process email title and content to classify and extract data.
    
    Args:
        request: RequestData containing internal data, title, and content
        
    Returns:
        ProcessResponse with classification results
    """
    try:
        logger.info(f"Processing request for mail_id: {request.internal.mail_id}")
        logger.debug(f"Title: {request.title[:100]}...")
        
        # Process the request using LangChain
        result = await classifier_service.process_request(
            internal_data=request.internal,
            title=request.title,
            content=request.content
        )
        
        logger.info(f"Successfully processed request with types: {result.types}")
        
        return ProcessResponse(
            success=True,
            data=result
        )
        
    except Exception as e:
        logger.error(f"Error processing request: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )

