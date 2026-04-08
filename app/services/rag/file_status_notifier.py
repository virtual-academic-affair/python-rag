import asyncio
import logging
from collections import defaultdict
from typing import Any, Dict

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class FileStatusNotifier:
    """Simple in-memory websocket notifier for upload progress by client_id."""

    def __init__(self) -> None:
        self._connections: dict[str, set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def connect(self, client_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections[client_id].add(websocket)
        logger.info(f"WS connected for client_id={client_id}")

    async def disconnect(self, client_id: str, websocket: WebSocket) -> None:
        async with self._lock:
            if client_id in self._connections and websocket in self._connections[client_id]:
                self._connections[client_id].remove(websocket)
                if not self._connections[client_id]:
                    self._connections.pop(client_id, None)
        logger.info(f"WS disconnected for client_id={client_id}")

    async def notify(self, client_id: str, payload: Dict[str, Any]) -> None:
        async with self._lock:
            targets = list(self._connections.get(client_id, set()))

        stale: list[WebSocket] = []
        for ws in targets:
            try:
                await ws.send_json(payload)
            except Exception:
                stale.append(ws)

        if stale:
            async with self._lock:
                for ws in stale:
                    self._connections.get(client_id, set()).discard(ws)


_notifier_instance: FileStatusNotifier | None = None


def get_file_status_notifier() -> FileStatusNotifier:
    global _notifier_instance
    if _notifier_instance is None:
        _notifier_instance = FileStatusNotifier()
    return _notifier_instance

