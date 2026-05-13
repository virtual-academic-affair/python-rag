import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.modules.email.notifier import get_email_status_notifier

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/email", tags=["Email"])


@router.websocket("/progress/{client_id}")
async def websocket_email_progress(websocket: WebSocket, client_id: str):
    """WebSocket channel to push email ingest processing status updates."""
    notifier = get_email_status_notifier()
    await notifier.connect(client_id, websocket)

    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await notifier.disconnect(client_id, websocket)
    except Exception as exc:
        logger.error("WS: Unexpected email progress error for client %s: %s", client_id, exc)
        await notifier.disconnect(client_id, websocket)

