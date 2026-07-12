from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.core.websocket_auth import authenticate_websocket_first_message


class FakeWebSocket:
    def __init__(self, message: str | Exception):
        self.message = message
        self.closed = None

    async def receive_text(self):
        if isinstance(self.message, Exception):
            raise self.message
        return self.message

    async def close(self, *, code: int, reason: str):
        self.closed = {"code": code, "reason": reason}


@pytest.mark.asyncio
async def test_websocket_auth_success():
    websocket = FakeWebSocket('{"type":"auth","token":"token"}')
    user = SimpleNamespace(role="admin")

    with patch("app.core.websocket_auth.verify_token_local", return_value=user):
        result = await authenticate_websocket_first_message(
            websocket,
            client_id="client-1",
            required_role="admin",
        )

    assert result is user
    assert websocket.closed is None


@pytest.mark.asyncio
async def test_websocket_auth_rejects_invalid_json():
    websocket = FakeWebSocket("{bad")

    result = await authenticate_websocket_first_message(websocket, client_id="client-1")

    assert result is None
    assert websocket.closed == {"code": 4001, "reason": "Invalid auth message format"}


@pytest.mark.asyncio
async def test_websocket_auth_rejects_missing_token():
    websocket = FakeWebSocket('{"type":"auth"}')

    result = await authenticate_websocket_first_message(websocket, client_id="client-1")

    assert result is None
    assert websocket.closed == {"code": 4001, "reason": "Expected type: auth and non-empty token"}


@pytest.mark.asyncio
async def test_websocket_auth_rejects_wrong_role():
    websocket = FakeWebSocket('{"type":"auth","token":"token"}')
    user = SimpleNamespace(role="student")

    with patch("app.core.websocket_auth.verify_token_local", return_value=user):
        result = await authenticate_websocket_first_message(
            websocket,
            client_id="client-1",
            required_role="admin",
        )

    assert result is None
    assert websocket.closed == {"code": 4001, "reason": "Admin role required"}
