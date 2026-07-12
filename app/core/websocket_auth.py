from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

from fastapi import HTTPException, WebSocket

from app.core.auth import JWTPayload, verify_token_local

logger = logging.getLogger(__name__)

AUTH_TIMEOUT_SECONDS = 10


async def authenticate_websocket_first_message(
    websocket: WebSocket,
    *,
    client_id: str,
    required_role: Optional[str] = None,
    timeout_seconds: int = AUTH_TIMEOUT_SECONDS,
) -> JWTPayload | None:
    try:
        raw_msg = await asyncio.wait_for(
            websocket.receive_text(),
            timeout=timeout_seconds,
        )
        auth_data = json.loads(raw_msg)
    except asyncio.TimeoutError:
        logger.warning("WS auth timeout for client %s", client_id)
        await websocket.close(code=4001, reason="Auth timeout")
        return None
    except Exception as exc:
        logger.warning("WS auth invalid message format for client %s: %s", client_id, exc)
        await websocket.close(code=4001, reason="Invalid auth message format")
        return None

    if auth_data.get("type") != "auth" or not auth_data.get("token"):
        logger.warning("WS auth missing type or token for client %s", client_id)
        await websocket.close(code=4001, reason="Expected type: auth and non-empty token")
        return None

    try:
        user = verify_token_local(auth_data["token"])
        if required_role and user.role != required_role:
            await websocket.close(code=4001, reason=f"{required_role.capitalize()} role required")
            return None
        return user
    except HTTPException as exc:
        logger.warning("WS auth failed for client %s: %s", client_id, exc.detail)
        await websocket.close(code=4001, reason="Invalid or expired token")
        return None
    except Exception as exc:
        logger.warning("WS auth failed for client %s: %s", client_id, exc)
        await websocket.close(code=4001, reason="Authentication error")
        return None
