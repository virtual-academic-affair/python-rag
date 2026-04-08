from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.services.rag.file_status_notifier import get_file_status_notifier

router = APIRouter(prefix="/files", tags=["Files"])


@router.websocket("/progress/{client_id}")
async def file_progress_ws(websocket: WebSocket, client_id: str):
    notifier = get_file_status_notifier()
    await notifier.connect(client_id, websocket)
    try:
        while True:
            # Keep connection alive and ignore incoming payloads.
            await websocket.receive_text()
    except WebSocketDisconnect:
        await notifier.disconnect(client_id, websocket)
    except Exception:
        await notifier.disconnect(client_id, websocket)

