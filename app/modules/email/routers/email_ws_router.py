import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.modules.email.utils.notifier import get_email_status_notifier
from app.core.auth import verify_token_local

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/email", tags=["Email"])


@router.websocket("/progress/{client_id}")
async def websocket_email_progress(websocket: WebSocket, client_id: str):
    """WebSocket channel to push email ingest processing status updates."""
    token = websocket.query_params.get("token")
    if not token:
        await websocket.accept()
        await websocket.close(code=1008, reason="Missing authentication token")
        return

    try:
        user = verify_token_local(token)
        if user.get("role") != "admin":
            await websocket.accept()
            await websocket.close(code=1008, reason="Admin role required")
            return
    except Exception as exc:
        logger.warning("WS auth failed for client %s: %s", client_id, exc)
        await websocket.accept()
        await websocket.close(code=1008, reason="Invalid authentication token")
        return

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
