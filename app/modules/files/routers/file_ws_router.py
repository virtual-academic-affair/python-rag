import asyncio
import json
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException
import logging
from app.modules.files.utils.notifier import get_file_status_notifier
from app.core.auth import verify_token_local

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/files", tags=["Files"])

AUTH_TIMEOUT_SECONDS = 10


@router.websocket("/progress/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    """
    WebSocket for real-time upload and processing progress notifications.
    Clients connect here with a unique client_id, and must authenticate by
    sending a JWT token in the first message.
    """
    await websocket.accept()
    
    # Wait for the first message containing authentication token
    try:
        raw_msg = await asyncio.wait_for(
            websocket.receive_text(),
            timeout=AUTH_TIMEOUT_SECONDS
        )
        auth_data = json.loads(raw_msg)
    except asyncio.TimeoutError:
        logger.warning(f"WS auth timeout for client {client_id}")
        await websocket.close(code=4001, reason="Auth timeout")
        return
    except Exception as e:
        logger.warning(f"WS auth invalid message format for client {client_id}: {e}")
        await websocket.close(code=4001, reason="Invalid auth message format")
        return

    if auth_data.get("type") != "auth" or not auth_data.get("token"):
        logger.warning(f"WS auth missing type or token for client {client_id}")
        await websocket.close(code=4001, reason="Expected type: auth and non-empty token")
        return

    try:
        verify_token_local(auth_data["token"])
    except HTTPException as e:
        logger.warning(f"WS auth failed for client {client_id}: {e.detail}")
        await websocket.close(code=4001, reason="Invalid or expired token")
        return
    except Exception as e:
        logger.error(f"WS auth error for client {client_id}: {e}")
        await websocket.close(code=4001, reason="Authentication error")
        return

    # Authentication successful
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
