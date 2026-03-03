"""API routes definitions"""
import logging
from fastapi import APIRouter, HTTPException, Depends, Header
from typing import Optional
from app.models.schemas import (
    AuthVerifyResponse,
    IngestMessage,
    InternalData,
    ProcessResponse,
    RequestData,
)
from app.services.orchestration.email_workflow_orchestrator import EmailWorkflowOrchestrator
from app.services.auth.auth_service import get_auth_service

logger = logging.getLogger(__name__)

router = APIRouter()


def get_classifier() -> EmailWorkflowOrchestrator:
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
    Verify JWT token by decoding it and checking in RabbitMQ.

    Args:
        authorization: Bearer token from Authorization header (format: "Bearer <token>")

    Returns:
        AuthVerifyResponse with user data from RabbitMQ if token is valid
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
    classifier_service: EmailWorkflowOrchestrator = Depends(get_classifier)
):
    """Process email title/content and return one of 4 supported labels."""
    try:
        logger.info(f"Processing request for mail_id: {request.internal.mail_id}")
        logger.debug(f"Title: {request.title[:100]}...")

        result = await classifier_service.process_request(
            internal_data=request.internal,
            title=request.title,
            content=request.content,
        )

        logger.info(f"Successfully processed request with label: {result.label}")
        return result

    except Exception as e:
        logger.error(f"Error processing request: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )


@router.post("/api/test/classification/ingested", response_model=ProcessResponse)
async def test_classification_from_ingested_payload(
    payload: IngestMessage,
    classifier_service: EmailWorkflowOrchestrator = Depends(get_classifier),
):
    """Test endpoint: process one RabbitMQ 'ingested' payload directly."""
    try:
        logger.info(
            "Test classification from ingested payload, messageId=%s",
            payload.data.email_id,
        )

        internal = InternalData(
            mail_id=str(payload.data.email_id),
            id_record=str(payload.data.email_id),
        )

        result = await classifier_service.process_request(
            internal_data=internal,
            title=payload.data.subject,
            content=payload.data.content,
        )

        return ProcessResponse(success=True, data=result)
    except Exception as e:
        logger.error("Error in test ingested classification endpoint: %s", str(e), exc_info=True)
        return ProcessResponse(success=False, error=f"Internal server error: {str(e)}")

