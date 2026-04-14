from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

class BaseSchema(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        serialize_by_alias=True,
    )

class UserContext(BaseSchema):
    user_id: str = Field(..., description="Anonymized user ID")
    name: str = Field(..., description="User name")
    cohort: str = Field(..., description="User cohort/class (e.g., K20)")
    role: str = Field(default="student", description="User role: student, lecture, admin")

class ChatHistoryItem(BaseSchema):
    role: str = Field(..., description="Message sender: user or assistant")
    content: str = Field(..., description="Message content")
    timestamp: Optional[str] = Field(default=None, description="Message timestamp")

class SourceCitation(BaseSchema):
    citation_id: int = Field(..., description="ID of citation [1], [2], etc.")
    title: Optional[str] = Field(None, description="Document title/name")
    text: Optional[str] = Field(None, description="Relevant text excerpt from document")
    url: Optional[str] = Field(None, description="R2 URL to view the document")
    file_id: Optional[str] = Field(None, description="File ID in database")

class ChatQueryRequest(BaseSchema):
    question: str = Field(..., min_length=1, max_length=2000, description="User's question")
    chat_history: List[ChatHistoryItem] = Field(default_factory=list, description="Recent chat history (max 10)")
    metadata_filter: Optional[Dict[str, List[str]]] = Field(None, description="Metadata filter as key-value pairs")

class ChatQueryResponse(BaseSchema):
    answer: str = Field(..., description="Generated answer from Gemini")
    sources: Optional[List[SourceCitation]] = Field(default=None, description="Document citations")
    steps: Optional[List[dict]] = Field(default=None, description="Agent reasoning steps (thoughts/calls)")
    token_usage: Optional[dict] = Field(default=None, description="Token consumption statistics")
    processing_time_ms: int = Field(..., description="Processing time in milliseconds")

class ChatStreamRequest(BaseSchema):
    question: str = Field(..., min_length=1, max_length=2000)
    chat_history: List[ChatHistoryItem] = Field(default_factory=list)
    metadata_filter: Optional[Dict[str, List[str]]] = Field(None, description="Metadata filter as key-value pairs")

class ChatRetrievePreviewRequest(BaseSchema):
    question: str = Field(..., min_length=1, max_length=2000)
    metadata_filter: Optional[Dict[str, List[str]]] = Field(None, description="Metadata filter as key-value pairs")
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
