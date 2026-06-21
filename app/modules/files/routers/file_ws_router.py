from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import logging
from app.modules.files.utils.notifier import get_file_status_notifier

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/files", tags=["Files"])


@router.websocket("/progress/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    """
    WebSocket for real-time upload and processing progress notifications.
    Clients connect here with a unique client_id to receive status updates.
    """
    notifier = get_file_status_notifier()
    await notifier.connect(client_id, websocket)
    
    try:
        while True:
            # We don't expect messages from the client, but we need to keep 
            # the connection open and detect disconnections.
            await websocket.receive_text()
    except WebSocketDisconnect:
        await notifier.disconnect(client_id, websocket)
    except Exception as e:
        logger.error(f"WS: Unexpected error for client {client_id}: {e}")
        await notifier.disconnect(client_id, websocket)
