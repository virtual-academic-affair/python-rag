from __future__ import annotations
from typing import Optional
from pydantic import BaseModel


class TopicCreateRequest(BaseModel):
    slug: str
    title: str
    summary: str = ""
    parent_key: Optional[str] = None  # node_key (slug) của cha, None = topic gốc


class TraverseRequest(BaseModel):
    question: str
    role: str = "student"  # student | lecture | admin
    enrollment_year: Optional[int] = None
    academic_year: Optional[int] = None


class ChatPreviewRequest(BaseModel):
    question: str
    role: str = "student"
    enrollment_year: Optional[int] = None
