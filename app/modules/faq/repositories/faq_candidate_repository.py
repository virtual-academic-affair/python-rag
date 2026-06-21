from __future__ import annotations

from typing import List, Optional, Tuple

from app.core.base_beanie_repository import BeanieRepository
from app.modules.faq.models.faq_candidate import FaqCandidateDocument


class FaqCandidateRepository(BeanieRepository[FaqCandidateDocument]):
    """Repository-specific queries for FAQ candidate documents."""

    document_class = FaqCandidateDocument

    async def list_candidates(
        self,
        status: Optional[str] = None,
        search_text: Optional[str] = None,
        skip: int = 0,
        limit: int = 20,
    ) -> Tuple[List[FaqCandidateDocument], int]:
        expressions = []
        if status:
            expressions.append(FaqCandidateDocument.status == status)

        query = FaqCandidateDocument.find(*expressions)
        if search_text:
            query = query.find({"$text": {"$search": search_text}}).sort(
                [("score", {"$meta": "textScore"})]
            )
        else:
            query = query.sort("-created_at")

        total = await query.count()
        items = await query.skip(skip).limit(limit).to_list()
        return items, total

    async def find_by_status(
        self,
        status: Optional[str] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> List[FaqCandidateDocument]:
        items, _ = await self.list_candidates(status=status, skip=skip, limit=limit)
        return items
