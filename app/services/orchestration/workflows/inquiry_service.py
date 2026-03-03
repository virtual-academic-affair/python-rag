"""Placeholder workflow service for inquiry label."""
import logging

logger = logging.getLogger(__name__)


class InquiryService:
    """Handle inquiry workflow (placeholder)."""

    async def process(self, title: str, content: str, message_id: int | None = None) -> None:
        logger.info(
            "Inquiry workflow placeholder: messageId=%s title=%r content_len=%s",
            message_id,
            title,
            len(content or ""),
        )

