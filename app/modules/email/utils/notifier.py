import asyncio
import logging
from collections import defaultdict
from typing import Any, Dict, Optional, Set

from fastapi import WebSocket

logger = logging.getLogger(__name__)

# Default shared channel for ingest processing notifications.
EMAIL_INGEST_PROGRESS_CHANNEL = "email-ingest"


class EmailStatusNotifier:
    """In-memory websocket notifier for email ingest processing status."""

    def __init__(self) -> None:
        self._connections: Dict[str, Set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def connect(self, client_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections[client_id].add(websocket)
        logger.info("WS: Client connected to email progress channel: %s", client_id)

    async def disconnect(self, client_id: str, websocket: WebSocket) -> None:
        async with self._lock:
            if client_id in self._connections:
                self._connections[client_id].discard(websocket)
                if not self._connections[client_id]:
                    del self._connections[client_id]
        logger.info("WS: Client disconnected from email progress channel: %s", client_id)

    async def notify(self, client_id: str, payload: Dict[str, Any]) -> None:
        async with self._lock:
            if client_id not in self._connections:
                return
            targets = list(self._connections[client_id])

        stale: Set[WebSocket] = set()
        for ws in targets:
            try:
                await ws.send_json(payload)
            except Exception as exc:
                logger.debug("WS: Failed to send email progress message to %s: %s", client_id, exc)
                stale.add(ws)

        if stale:
            async with self._lock:
                if client_id in self._connections:
                    self._connections[client_id].difference_update(stale)
                    if not self._connections[client_id]:
                        del self._connections[client_id]


_notifier_instance: Optional[EmailStatusNotifier] = None


def get_email_status_notifier() -> EmailStatusNotifier:
    global _notifier_instance
    if _notifier_instance is None:
        _notifier_instance = EmailStatusNotifier()
    return _notifier_instance

