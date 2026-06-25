from typing import Optional, Literal
from pydantic import Field
from app.core.base_schema import BaseSchema

class ChatStreamRequest(BaseSchema):
    question: str = Field(..., min_length=1, max_length=2000)
    session_id: Optional[str] = Field(default=None, description="Chat session ID")
    resolve_citations: Optional[bool] = Field(default=False, description="Whether to resolve citations to links")
    citation_link_type: Literal["original", "markdown"] = Field(default="markdown", description="Type of link to use for citations: 'original' or 'markdown'")
