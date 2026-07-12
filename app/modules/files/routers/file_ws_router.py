from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import logging
from app.core.websocket_auth import authenticate_websocket_first_message
from app.modules.files.utils.notifier import get_file_status_notifier

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/files", tags=["Files"])


@router.websocket("/progress/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    """
    WebSocket for real-time upload and processing progress notifications.
    Clients connect here with a unique client_id, and must authenticate by
    sending a JWT token in the first message.
    """
    await websocket.accept()

    user = await authenticate_websocket_first_message(websocket, client_id=client_id)
    if not user:
        return

    await websocket.send_json({"type": "auth_ok"})
    logger.info(f"WS: Authenticated client {client_id}")

    notifier = get_file_status_notifier()
    await notifier.connect(client_id, websocket)
    
    try:
        while True:
            # Keep connection open and detect disconnections
            await websocket.receive_text()
    except WebSocketDisconnect:
        await notifier.disconnect(client_id, websocket)
    except Exception as e:
        logger.error(f"WS: Unexpected error for client {client_id}: {e}")
        await notifier.disconnect(client_id, websocket)
