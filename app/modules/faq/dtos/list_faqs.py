from typing import List
from app.core.base_schema import BaseSchema
from app.modules.faq.dtos.faq_out import FaqResponse, FaqCandidateResponse

class FaqListResponse(BaseSchema):
    items: List[FaqResponse]
    total: int
    page: int
    limit: int

class FaqCandidateListResponse(BaseSchema):
    items: List[FaqCandidateResponse]
    total: int
    page: int
    limit: int
