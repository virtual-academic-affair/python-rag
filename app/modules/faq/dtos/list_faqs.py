from typing import List
from app.core.base_schema import BaseSchema
from app.modules.faq.dtos.faq_out import FaqResponse

class FaqListResponse(BaseSchema):
    items: List[FaqResponse]
    total: int
    page: int
    limit: int
