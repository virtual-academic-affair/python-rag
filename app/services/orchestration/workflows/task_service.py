"""Placeholder workflow service for task label."""
import logging

logger = logging.getLogger(__name__)


class TaskService:
    """Handle task workflow (placeholder)."""

    async def process(self, title: str, content: str, message_id: int | None = None) -> None:
        logger.info(
            "Task workflow placeholder: messageId=%s title=%r content_len=%s",
            message_id,
            title,
            len(content or ""),
        )

