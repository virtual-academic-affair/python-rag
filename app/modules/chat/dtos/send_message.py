from typing import List, Optional
from pydantic import Field
from app.core.base_schema import BaseSchema
from app.modules.rag.query.dtos import SourceCitation
from app.modules.rag.query.dtos import TokenUsage
from app.modules.chat.dtos.faq_recommendation import FaqRecommendation

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
    to_rich_text: Optional[bool] = Field(default=False, description="Convert final markdown answer to HTML rich text")

class ChatQueryResponse(BaseSchema):
    answer: str = Field(..., description="Generated answer from Gemini")
    session_id: str = Field(..., description="Chat session ID")
    source: str = Field(default="llm", description="Source of the answer: 'llm' | 'faq' | 'bypass'")
    sources: Optional[List[SourceCitation]] = Field(default=None, description="Document citations")
    steps: Optional[List[dict]] = Field(default=None, description="RAG activity timeline: analysis, Corpus traversal, FAQ/file retrieval, and document reads")
    token_usage: Optional[TokenUsage] = Field(default=None, description="Token consumption statistics")
    processing_time_ms: int = Field(..., description="Processing time in milliseconds")
    faq_recommendation: Optional[FaqRecommendation] = Field(
        default=None,
        description="Draft-ready FAQ metadata derived from the answer's actual sources",
    )
