from typing import Optional, List, Dict, Any
from pydantic import Field
from app.core.base_document import BaseDocument
from pymongo import IndexModel, ASCENDING, DESCENDING

from app.modules.chat.dtos.faq_recommendation import FaqRecommendation
from app.modules.chat.dtos.send_message import TokenUsage
from app.modules.rag.query.dtos import SourceCitation

class ChatMessageDocument(BaseDocument):
    session_id: str
    user_id: str
    role: str
    content: str
    message_type: str = "text"
    token_usage: Optional[TokenUsage] = None
    sources: List[SourceCitation] = Field(default_factory=list)
    steps: List[Dict[str, Any]] = Field(default_factory=list)
    processing_time_ms: Optional[int] = None
    faq_recommendation: Optional[FaqRecommendation] = None
    sequence: int

    class Settings:
        name = "chat_messages"
        indexes = [
            IndexModel([("session_id", ASCENDING), ("user_id", ASCENDING), ("sequence", ASCENDING)], unique=True, name="session_id_1_user_id_1_sequence_1"),
            IndexModel([("session_id", ASCENDING), ("user_id", ASCENDING), ("message_type", ASCENDING), ("sequence", DESCENDING)], name="session_id_1_user_id_1_message_type_1_sequence_-1"),
        ]
