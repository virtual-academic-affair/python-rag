from __future__ import annotations

from typing import Any, List, Optional, Tuple

from app.core.base_beanie_repository import BeanieRepository
from app.modules.faq.models.faq import FaqDocument


class FaqRepository(BeanieRepository[FaqDocument]):
    """Repository-specific queries for FAQ documents."""

    document_class = FaqDocument

    async def find_by_unaccented_question(self, question_unaccented: str) -> Optional[FaqDocument]:
        return await FaqDocument.find_one(FaqDocument.question_unaccented == question_unaccented)

    async def find_by_qdrant_point_id(self, point_id: str) -> Optional[FaqDocument]:
        return await FaqDocument.find_one(FaqDocument.qdrant_point_id == point_id)

    async def list_faqs(
        self,
        is_active: Optional[bool] = None,
        metadata_filter: Optional[dict[str, Any]] = None,
        search_text: Optional[str] = None,
        skip: int = 0,
        limit: int = 20,
    ) -> Tuple[List[FaqDocument], int]:
        expressions = []
        if is_active is not None:
            expressions.append(FaqDocument.is_active == is_active)

        query = FaqDocument.find(*expressions)
        if metadata_filter:
            query = query.find(metadata_filter)

        if search_text:
            query = query.find({"$text": {"$search": search_text}}).sort(
                [("score", {"$meta": "textScore"})]
            )
        else:
            query = query.sort("-created_at")

        total = await query.count()
        items = await query.skip(skip).limit(limit).to_list()
        return items, total

    async def list_active(self, skip: int = 0, limit: int = 100) -> List[FaqDocument]:
        return (
            await FaqDocument.find(FaqDocument.is_active == True)
            .sort("-created_at")
            .skip(skip)
            .limit(limit)
            .to_list()
        )

    async def increment_view_count(self, faq_id: str) -> bool:
        doc = await self.find_by_id(faq_id)
        if not doc:
            return False
        doc.view_count += 1
        await self.save(doc)
        return True
