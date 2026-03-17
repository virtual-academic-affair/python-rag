"""Inquiry workflow service: RAG draft generation + gRPC create Gmail draft."""
import logging
from typing import Dict, Any, Optional

from app.services.rag.email_draft_service import draft_inquiry_email_reply, extract_inquiry_intent, extract_inquiry_types
from app.services.integrations.grpc_client import get_grpc_inquiry_client

logger = logging.getLogger(__name__)


class InquiryService:

    async def process(
        self,
        title: str,
        content: str,
        message_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        # 1a. Extract the main question/intent
        extracted_question = await extract_inquiry_intent(title, content)
        if extracted_question:
            logger.info("Extracted inquiry intent/question: %r", extracted_question)

        # 1b. Extract inquiry types/categories
        inquiry_types = await extract_inquiry_types(title, content)
        if inquiry_types:
            logger.info("Extracted inquiry types: %r", inquiry_types)
    
        # 2. Generate email draft via RAG
        draft_result = await draft_inquiry_email_reply(
            subject=title,
            body=content,
            extracted_question=extracted_question,
            inquiry_types=inquiry_types,
        )
        logger.info(
            "Inquiry draft generated: answer_len=%d sources=%d",
            len(draft_result["answer"]),
            len(draft_result["sources"]),
        )

        # 3. Push draft to Inquiry via nest-api gRPC (graceful skip if not yet implemented)
        if message_id is not None:
            client = get_grpc_inquiry_client()
            await client.create_inquiry(
                message_id=message_id,
                answer=draft_result["answer"],
                extracted_question=extracted_question,
                inquiry_types=inquiry_types,
                sources=draft_result["sources"],
            )

        return draft_result

