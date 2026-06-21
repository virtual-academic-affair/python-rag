import asyncio
import logging
from collections import defaultdict
from typing import Any, Dict, Optional, Set

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class FileStatusNotifier:
    """In-memory websocket notifier for file processing progress in python-rag."""

    def __init__(self) -> None:
        self._connections: Dict[str, Set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def connect(self, client_id: str, websocket: WebSocket) -> None:
        """Accept and register a new websocket connection."""
        await websocket.accept()
        async with self._lock:
            self._connections[client_id].add(websocket)
        logger.info(f"WS: Client connected to progress channel: {client_id}")

    async def disconnect(self, client_id: str, websocket: WebSocket) -> None:
        """Unregister a websocket connection."""
        async with self._lock:
            if client_id in self._connections:
                self._connections[client_id].discard(websocket)
                if not self._connections[client_id]:
                    del self._connections[client_id]
        logger.info(f"WS: Client disconnected from progress channel: {client_id}")

    async def notify(self, client_id: str, payload: Dict[str, Any]) -> None:
        """Broadcast progress payload to all connections for a specific client_id."""
        async with self._lock:
            if client_id not in self._connections:
                return
            targets = list(self._connections[client_id])

        stale: Set[WebSocket] = set()
        for ws in targets:
            try:
                await ws.send_json(payload)
            except Exception as e:
                logger.debug(f"WS: Failed to send message to {client_id}: {e}")
                stale.add(ws)

        if stale:
            async with self._lock:
                if client_id in self._connections:
                    self._connections[client_id].difference_update(stale)
                    if not self._connections[client_id]:
                        del self._connections[client_id]


# Singleton instance and accessor
_notifier_instance: Optional[FileStatusNotifier] = None


def get_file_status_notifier() -> FileStatusNotifier:
    """Get the singleton instance of FileStatusNotifier."""
    global _notifier_instance
    if _notifier_instance is None:
        _notifier_instance = FileStatusNotifier()
    return _notifier_instance
