"""
Classification Endpoints - Email processing and classification workflow.
"""

import logging
from fastapi import APIRouter, HTTPException, Depends, Request
from google.genai.errors import APIError

from app.modules.email.models.email_types import IngestMessage, RequestData
from app.modules.email.models.email_out import ProcessResponse
from app.modules.email.services.email_orchestrator_service import EmailWorkflowOrchestrator
from app.core.exceptions import handle_google_api_error

from app.core.dependencies import require_admin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/email", tags=["Email Classification"])


def get_classifier(request: Request) -> EmailWorkflowOrchestrator:
    """Dependency to get the email orchestrator instance from app state."""
    orchestrator = getattr(request.app.state, "email_orchestrator", None)
    if orchestrator is None:
        raise HTTPException(status_code=500, detail="Classifier not initialized in app state")
    return orchestrator


@router.post("/process")
async def process_request(
    request: RequestData,
    classifier_service: EmailWorkflowOrchestrator = Depends(get_classifier),
    _admin: dict = Depends(require_admin),
):
    """Process email title/content and return one of 4 supported labels."""
    try:
        logger.info("Processing manual request")
        logger.debug(f"Title: {request.title[:100]}...")

        result = await classifier_service.process_request(
            message_id=request.message_id,
            title=request.title,
            content=request.content,
            sender_email="",  # Manual endpoint - no sender info
            sender_name="",
        )

        label_info = getattr(result, "label", None) or getattr(result, "labels", None)
        logger.info(f"Successfully processed request with label: {label_info}")
        return result

    except Exception as e:
        logger.error(f"Error processing request: {str(e)}", exc_info=True)
        if isinstance(e, APIError):
            raise handle_google_api_error(e, prefix="Internal server error: ")
            
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}",
        )


@router.post("/test/ingested", response_model=ProcessResponse)
async def test_classification_from_ingested_payload(
    payload: IngestMessage,
    classifier_service: EmailWorkflowOrchestrator = Depends(get_classifier),
    _admin: dict = Depends(require_admin),
):
    """Test endpoint: process one RabbitMQ 'ingested' payload directly."""
    try:
        message_id = payload.data.message_id
        logger.info(
            "Test classification from ingested payload, messageId=%s",
            message_id,
        )

        result = await classifier_service.process_request(
            message_id=message_id,
            title=payload.data.subject,
            content=payload.data.content,
            sender_email=payload.data.sender_email,
            sender_name=payload.data.sender_name,
        )

        return ProcessResponse(success=True, data=result)
    except Exception as e:
        logger.error("Error in test ingested classification endpoint: %s", str(e), exc_info=True)
        if isinstance(e, APIError):
            raise handle_google_api_error(e, prefix="Internal server error: ")
            
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}",
        )
