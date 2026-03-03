"""Placeholder workflow service for other label."""
import logging

logger = logging.getLogger(__name__)


class OtherService:
    """Handle other workflow (placeholder)."""

    async def process(self, title: str, content: str, message_id: int | None = None) -> None:
        logger.info(
            "Other workflow placeholder: messageId=%s title=%r content_len=%s",
            message_id,
            title,
            len(content or ""),
        )

