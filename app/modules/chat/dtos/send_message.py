from typing import List, Optional, Literal
from pydantic import Field
from app.core.base_schema import BaseSchema
from app.modules.rag.query.dtos import SourceCitation

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
    citation_link_type: Literal["original", "markdown"] = Field(default="markdown", description="Type of link to use for citations: 'original' or 'markdown'")
    to_rich_text: Optional[bool] = Field(default=False, description="Convert final markdown answer to HTML rich text")

class TokenUsage(BaseSchema):
    prompt_tokens: int = Field(..., description="Number of prompt tokens used")
    completion_tokens: int = Field(..., description="Number of completion tokens used")
    total_tokens: int = Field(..., description="Total number of tokens used")

class ChatQueryResponse(BaseSchema):
    answer: str = Field(..., description="Generated answer from Gemini")
    session_id: str = Field(..., description="Chat session ID")
    source: str = Field(default="llm", description="Source of the answer: 'llm' | 'faq' | 'bypass'")
    sources: Optional[List[SourceCitation]] = Field(default=None, description="Document citations")
    steps: Optional[List[dict]] = Field(default=None, description="Agent reasoning steps (thoughts/calls)")
    token_usage: Optional[TokenUsage] = Field(default=None, description="Token consumption statistics")
    processing_time_ms: int = Field(..., description="Processing time in milliseconds")
