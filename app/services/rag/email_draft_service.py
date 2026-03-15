"""
Email Draft Service - Pure function for generating email replies.
Called internally by orchestrator when email is classified as 'inquiry'.
"""

import logging
from typing import Dict, Any, Optional

from app.services.rag.gemini_service import gemini_service
from app.utils.store_utils import resolve_store
from app.utils.filter_builder import convert_metadata_filter_to_gemini_format

logger = logging.getLogger(__name__)


async def draft_inquiry_email_reply(
    subject: str,
    body: str,
    sender_name: Optional[str] = None,
    sender_email: Optional[str] = None,
    additional_context: Optional[str] = None,
    store_id: Optional[str] = None,
    metadata_filter: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Draft an email reply for inquiry-classified emails using RAG.
    
    This is a pure function (not an HTTP endpoint) called by the 
    email workflow orchestrator when label=inquiry.
    
    Args:
        subject: Original email subject
        body: Original email body
        sender_name: Sender's name (optional)
        sender_email: Sender's email (optional)
        additional_context: Extra instructions for drafting (optional)
        store_id: Store ID for RAG (optional, uses default if not provided)
        metadata_filter: Metadata filter dict (e.g., {"department": "Đào tạo"})
    
    Returns:
        Dict containing:
        - draft_subject: str - Suggested reply subject
        - draft_body: str - Drafted email body
        - sources: List[Dict] - RAG sources with citations
        - token_usage: Dict - Token statistics (optional)
    
    Raises:
        Exception: If drafting fails
    """
    # Resolve store (request → default store → error)
    store_id_resolved, store_name = await resolve_store(store_id)
    logger.info(f"Drafting email reply using store: {store_name}")

    # Convert metadata filter from dict to Gemini format string
    gemini_filter = convert_metadata_filter_to_gemini_format(metadata_filter)

    # Build additional context with sender info
    context_parts = []
    if sender_name:
        context_parts.append(f"Người gửi: {sender_name}")
    if sender_email:
        context_parts.append(f"Email: {sender_email}")
    if additional_context:
        context_parts.append(additional_context)

    full_context = " | ".join(context_parts) if context_parts else None

    # Generate draft using Gemini RAG
    result = await gemini_service.draft_email_reply(
        original_subject=subject,
        original_body=body,
        sender_name=sender_name,
        additional_context=full_context,
        store_name=store_name,
        metadata_filter=gemini_filter,
    )

    if result is None:
        raise ValueError("Email draft service returned no result from Gemini")

    logger.info(
        f"Email draft generated successfully. "
        f"Sources: {len(result.get('sources', []))} documents"
    )

    return result
