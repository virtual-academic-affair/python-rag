"""API routes definitions"""
import logging
from fastapi import APIRouter, HTTPException, Depends, Header
from typing import Optional
from app.models.schemas import RequestData, ProcessResponse, AuthVerifyResponse
from app.services.langchain_service import LangChainClassifier
from app.services.auth_service import get_auth_service

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


@router.post("/api/auth/verify", response_model=AuthVerifyResponse)
async def verify_token(
    authorization: Optional[str] = Header(None),
    auth_service = Depends(get_auth_service)
):
    """
    Verify JWT token by decoding it and checking in Redis.
    
    Args:
        authorization: Bearer token from Authorization header (format: "Bearer <token>")
        
    Returns:
        AuthVerifyResponse with user data from Redis if token is valid
    """
    try:
        # Extract token from Authorization header
        if not authorization:
            logger.warning("Missing Authorization header")
            return AuthVerifyResponse(
                success=False,
                error="Missing Authorization header"
            )
        
        # Check if it's a Bearer token
        if not authorization.startswith("Bearer "):
            logger.warning("Invalid Authorization header format")
            return AuthVerifyResponse(
                success=False,
                error="Authorization header must start with 'Bearer '"
            )
        
        # Extract token
        token = authorization.replace("Bearer ", "").strip()
        
        if not token:
            logger.warning("Empty token")
            return AuthVerifyResponse(
                success=False,
                error="Token is empty"
            )
        
        # Verify token
        user_data = auth_service.verify_token(token)
        
        logger.info(f"Token verified successfully")
        return AuthVerifyResponse(
            success=True,
            data=user_data
        )
        
    except HTTPException as e:
        # Re-raise HTTP exceptions (from auth_service)
        logger.warning(f"Token verification failed: {e.detail}")
        return AuthVerifyResponse(
            success=False,
            error=e.detail
        )
    except Exception as e:
        logger.error(f"Error verifying token: {str(e)}", exc_info=True)
        return AuthVerifyResponse(
            success=False,
            error=f"Internal server error: {str(e)}"
        )


@router.post("/process")
async def process_request(
    request: RequestData,
    classifier_service: LangChainClassifier = Depends(get_classifier)
):
    """
    Process email title and content to classify and extract data.
    
    Args:
        request: RequestData containing internal data, title, and content
        
    Returns:
        Direct response object with classification results (ClassRegistrationResponse or OtherResponse)
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
        
        # Return the result directly (it will be serialized by FastAPI)
        return result
        
    except Exception as e:
        logger.error(f"Error processing request: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )

