"""
Classification Endpoints - Email processing and classification workflow.
"""

import logging
from fastapi import APIRouter, HTTPException, Depends

from app.models.schemas import (
    IngestMessage,
    InternalData,
    ProcessResponse,
    RequestData,
)
from app.services.orchestration.email_workflow_orchestrator import EmailWorkflowOrchestrator

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Email Classification"])


def get_classifier() -> EmailWorkflowOrchestrator:
    """Dependency to get the email orchestrator instance."""
    from app.main import email_orchestrator
    if email_orchestrator is None:
        raise HTTPException(status_code=500, detail="Classifier not initialized")
    return email_orchestrator


@router.post("/process")
async def process_request(
    request: RequestData,
    classifier_service: EmailWorkflowOrchestrator = Depends(get_classifier),
):
    """Process email title/content and return one of 4 supported labels."""
    try:
        logger.info(f"Processing request for mail_id: {request.internal.mail_id}")
        logger.debug(f"Title: {request.title[:100]}...")

        result = await classifier_service.process_request(
            internal_data=request.internal,
            title=request.title,
            content=request.content,
            sender_email="",  # Manual endpoint - no sender info
            sender_name="",
        )

        logger.info(f"Successfully processed request with label: {result.label}")
        return result

    except Exception as e:
        logger.error(f"Error processing request: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}",
        )


@router.post("/api/test/classification/ingested", response_model=ProcessResponse)
async def test_classification_from_ingested_payload(
    payload: IngestMessage,
    classifier_service: EmailWorkflowOrchestrator = Depends(get_classifier),
):
    """Test endpoint: process one RabbitMQ 'ingested' payload directly."""
    try:
        email_id = payload.data.id
        logger.info(
            "Test classification from ingested payload, id=%s",
            email_id,
        )

        internal = InternalData(
            mail_id=str(email_id),
            id_record=str(email_id),
        )

        result = await classifier_service.process_request(
            internal_data=internal,
            title=payload.data.subject,
            content=payload.data.content,
            sender_email=payload.data.sender_email,
            sender_name=payload.data.sender_name,
        )

        return ProcessResponse(success=True, data=result)
    except Exception as e:
        logger.error("Error in test ingested classification endpoint: %s", str(e), exc_info=True)
        return ProcessResponse(success=False, error=f"Internal server error: {str(e)}")
