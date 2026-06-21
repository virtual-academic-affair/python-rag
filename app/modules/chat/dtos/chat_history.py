from typing import Any, Dict, List, Optional
from pydantic import Field
from app.core.base_schema import BaseSchema

class ChatPaginationRequest(BaseSchema):
    page: int = Field(default=1, ge=1, description="Page number")
    page_size: int = Field(default=20, ge=1, le=100, description="Items per page")

class ChatSessionItem(BaseSchema):
    session_id: str
    title: Optional[str] = None
    status: str
    message_count: int
    last_message_at: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

class ChatSessionListResponse(BaseSchema):
    page: int
    page_size: int
    total: int
    items: List[ChatSessionItem] = Field(default_factory=list)

class ChatMessageItem(BaseSchema):
    role: str
    content: str
    sequence: int
    message_type: str = Field(default="text", description="Message type: text or thinking")
    token_usage: Optional[Dict[str, Any]] = None
    sources: Optional[List[Dict[str, Any]]] = Field(default=None)
    steps: Optional[List[Dict[str, Any]]] = Field(default=None, description="Pipeline steps persisted to DB: query_analysis, faq_check, retrieval, call")
    processing_time_ms: Optional[int] = None
    created_at: Optional[str] = None

class ChatMessageListResponse(BaseSchema):
    session_id: str
    page: int
    page_size: int
    total: int
    items: List[ChatMessageItem] = Field(default_factory=list)

class ChatSessionRenameRequest(BaseSchema):
    title: str = Field(..., min_length=1, max_length=200)

class ChatSessionMutationResponse(BaseSchema):
    session_id: str
    success: bool
