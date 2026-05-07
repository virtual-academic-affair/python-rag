from typing import Any, Dict, List, Optional
from pydantic import Field
from app.core.schemas import BaseSchema
from app.modules.rag.retrieval.schemas import SourceCitation
from app.modules.metadata.schemas import FaqMetadataSchema

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
    chat_history: List[ChatHistoryItem] = Field(default_factory=list, description="Recent chat history (max 10)")
    metadata_filter: Optional[FaqMetadataSchema] = Field(None, description="Metadata filter using fixed schema")

class ChatQueryResponse(BaseSchema):
    answer: str = Field(..., description="Generated answer from Gemini")
    source: str = Field(default="llm", description="Source of the answer: 'llm', 'faq', or 'bypass'")
    sources: Optional[List[SourceCitation]] = Field(default=None, description="Document citations")
    steps: Optional[List[dict]] = Field(default=None, description="Agent reasoning steps (thoughts/calls)")
    token_usage: Optional[dict] = Field(default=None, description="Token consumption statistics")
    processing_time_ms: int = Field(..., description="Processing time in milliseconds")

class ChatStreamRequest(BaseSchema):
    question: str = Field(..., min_length=1, max_length=2000)
    chat_history: List[ChatHistoryItem] = Field(default_factory=list)
    metadata_filter: Optional[FaqMetadataSchema] = Field(None, description="Metadata filter using fixed schema")

class ChatRetrievePreviewRequest(BaseSchema):
    question: str = Field(..., min_length=1, max_length=2000)
    metadata_filter: Optional[FaqMetadataSchema] = Field(None, description="Metadata filter using fixed schema")
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
