from typing import Optional, List, Dict, Any
from pydantic import Field
from app.core.base_document import BaseDocument
from pymongo import IndexModel, ASCENDING, DESCENDING

class ChatMessageDocument(BaseDocument):
    session_id: str
    user_id: str
    role: str
    content: str
    message_type: str = "text"
    token_usage: Optional[Dict[str, Any]] = None
    sources: List[Dict[str, Any]] = Field(default_factory=list)
    steps: List[Dict[str, Any]] = Field(default_factory=list)
    processing_time_ms: Optional[int] = None
    sequence: int

    class Settings:
        name = "chat_messages"
        indexes = [
            IndexModel([("session_id", ASCENDING), ("user_id", ASCENDING), ("sequence", ASCENDING)], name="session_id_1_user_id_1_sequence_1"),
            IndexModel([("session_id", ASCENDING), ("user_id", ASCENDING), ("message_type", ASCENDING), ("sequence", DESCENDING)], name="session_id_1_user_id_1_message_type_1_sequence_-1"),
        ]
