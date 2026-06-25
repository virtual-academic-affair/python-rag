import asyncio
import json
import logging
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from app.modules.email.utils.notifier import get_email_status_notifier
from app.core.auth import verify_token_local

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/email", tags=["Email"])

AUTH_TIMEOUT_SECONDS = 10


@router.websocket("/progress/{client_id}")
async def websocket_email_progress(websocket: WebSocket, client_id: str):
    """
    WebSocket channel to push email ingest processing status updates.
    Clients must authenticate by sending an admin JWT token in the first message.
    """
    await websocket.accept()

    try:
        raw_msg = await asyncio.wait_for(
            websocket.receive_text(),
            timeout=AUTH_TIMEOUT_SECONDS,
        )
        auth_data = json.loads(raw_msg)
    except asyncio.TimeoutError:
        logger.warning("Email WS auth timeout for client %s", client_id)
        await websocket.close(code=4001, reason="Auth timeout")
        return
    except Exception as exc:
        logger.warning("Email WS auth invalid message format for client %s: %s", client_id, exc)
        await websocket.close(code=4001, reason="Invalid auth message format")
        return

    if auth_data.get("type") != "auth" or not auth_data.get("token"):
        logger.warning("Email WS auth missing type or token for client %s", client_id)
        await websocket.close(code=4001, reason="Expected type: auth and non-empty token")
        return

    try:
        user = verify_token_local(auth_data["token"])
        if user.role != "admin":
            await websocket.close(code=4001, reason="Admin role required")
            return
    except HTTPException as exc:
        logger.warning("Email WS auth failed for client %s: %s", client_id, exc.detail)
        await websocket.close(code=4001, reason="Invalid or expired token")
        return
    except Exception as exc:
        logger.warning("Email WS auth failed for client %s: %s", client_id, exc)
        await websocket.close(code=4001, reason="Authentication error")
        return

    await websocket.send_json({"type": "auth_ok"})
    logger.info("WS: Authenticated email progress client %s", client_id)

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
