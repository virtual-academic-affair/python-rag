from typing import Any, Dict, List, Optional
from pydantic import Field
from app.core.schemas import BaseSchema
from app.modules.rag.retrieval.schemas import SourceCitation
from app.modules.metadata.schemas import UnifiedFilterSchema

class UserContext(BaseSchema):
    user_id: str = Field(..., description="Anonymized user ID")
    name: str = Field(..., description="User name")
    enrollment_year: Optional[int] = Field(None, description="User enrollment year (e.g., 2020)")
    role: str = Field(default="student", description="User role: student, lecture, admin")

class ChatHistoryItem(BaseSchema):
    role: str = Field(..., description="Message sender: user or assistant")
    content: str = Field(..., description="Message content")
    timestamp: Optional[str] = Field(default=None, description="Message timestamp")

class ChatQueryRequest(BaseSchema):
    question: str = Field(..., min_length=1, max_length=2000, description="User's question")
    session_id: Optional[str] = Field(default=None, description="Chat session ID")
    resolve_citations: Optional[bool] = Field(default=False, description="Whether to resolve citations to links")
    citation_link_type: Optional[str] = Field(default="markdown", description="Type of link to use for citations: 'original' or 'markdown'")
    to_rich_text: Optional[bool] = Field(default=False, description="Convert final markdown answer to HTML rich text")

class ChatQueryResponse(BaseSchema):
    answer: str = Field(..., description="Generated answer from Gemini")
    session_id: str = Field(..., description="Chat session ID")
    source: str = Field(default="llm", description="Source of the answer: 'llm' | 'faq'")
    sources: Optional[List[SourceCitation]] = Field(default=None, description="Document citations")
    steps: Optional[List[dict]] = Field(default=None, description="Agent reasoning steps (thoughts/calls)")
    token_usage: Optional[dict] = Field(default=None, description="Token consumption statistics")
    processing_time_ms: int = Field(..., description="Processing time in milliseconds")

class ChatStreamRequest(BaseSchema):
    question: str = Field(..., min_length=1, max_length=2000)
    session_id: Optional[str] = Field(default=None, description="Chat session ID")
    resolve_citations: Optional[bool] = Field(default=False, description="Whether to resolve citations to links")
    citation_link_type: Optional[str] = Field(default="markdown", description="Type of link to use for citations: 'original' or 'markdown'")

class ChatRetrievePreviewRequest(BaseSchema):
    question: str = Field(..., min_length=1, max_length=2000)
    metadata_filter: Optional[UnifiedFilterSchema] = Field(None, description="Metadata filter using fixed schema")
    top_k: Optional[int] = Field(default=None, ge=1, le=20)
    min_score: Optional[float] = Field(default=None, ge=0)
    include_explain: bool = Field(default=True, description="Whether to include score breakdown details")

class ChatRetrievePreviewItem(BaseSchema):
    rank: int
    file_id: Optional[str] = None
    file_name: Optional[str] = None
    section_path: Optional[str] = None
    score: Optional[float] = None
    explain: Optional[Dict[str, Any]] = None
    text: str

class ChatRetrievePreviewResponse(BaseSchema):
    query: str
    top_k: int
    min_score: float
    count: int
    cache_stats: Optional[Dict[str, Any]] = None
    items: List[ChatRetrievePreviewItem] = Field(default_factory=list)


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