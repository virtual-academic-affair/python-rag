from typing import Optional, Dict, Any
from datetime import datetime, timezone
from pydantic import Field
from app.core.base_document import BaseDocument
from pymongo import IndexModel, ASCENDING, DESCENDING

class ChatSessionDocument(BaseDocument):
    session_id: str
    user_id: str
    title: Optional[str] = None
    status: str = "active"
    message_count: int = 0
    last_message_at: Optional[datetime] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    class Settings:
        name = "chat_sessions"
        indexes = [
            IndexModel([("session_id", ASCENDING), ("user_id", ASCENDING)], unique=True, name="idx_chat_sessions_session_user_unique"),
            IndexModel([("user_id", ASCENDING), ("status", ASCENDING)], name="idx_chat_sessions_user_status"),
            IndexModel([("user_id", ASCENDING), ("last_message_at", DESCENDING)], name="idx_chat_sessions_user_last_message"),
        ]
