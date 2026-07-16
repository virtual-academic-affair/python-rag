from typing import Optional
from pydantic import Field
from app.core.base_schema import BaseSchema

class ChatStreamRequest(BaseSchema):
    question: str = Field(..., min_length=1, max_length=2000)
    session_id: Optional[str] = Field(default=None, description="Chat session ID")
