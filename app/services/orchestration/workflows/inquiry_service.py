"""Inquiry workflow service: RAG draft generation + gRPC create Gmail draft."""
import logging
from typing import Dict, Any, Optional

from app.services.rag.email_draft_service import draft_inquiry_email_reply
from app.services.grpc.nest_email_client import get_grpc_email_client

logger = logging.getLogger(__name__)


class InquiryService:

    async def process(
        self,
        title: str,
        content: str,
        message_id: Optional[int] = None,
        sender_email: str = "",
        sender_name: str = "",
    ) -> Dict[str, Any]:
        # 1. Generate email draft via RAG
        draft_result = await draft_inquiry_email_reply(
            subject=title,
            body=content,
            sender_email=sender_email,
            sender_name=sender_name,
        )
        logger.info(
            "Inquiry draft generated: subject=%r body_len=%d sources=%d",
            draft_result["draft_subject"],
            len(draft_result["draft_body"]),
            len(draft_result["sources"]),
        )

        # 2. Push draft to Gmail via nest-api gRPC (graceful skip if not yet implemented)
        if message_id is not None:
            client = get_grpc_email_client()
            await client.create_draft(
                message_id=message_id,
                draft_subject=draft_result["draft_subject"],
                draft_body=draft_result["draft_body"],
            )

        return draft_result

