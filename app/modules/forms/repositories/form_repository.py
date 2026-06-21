from __future__ import annotations

from typing import List, Optional, Tuple

from app.core.base_beanie_repository import BeanieRepository
from app.modules.forms.models.form import FormDocument


class FormRepository(BeanieRepository[FormDocument]):
    document_class = FormDocument

    async def find_by_document_type(self, document_type: str) -> Optional[FormDocument]:
        return await FormDocument.find_one(FormDocument.documentType == document_type)

    async def find_one_by_content_link(self, document_type: str, content_link: str) -> Optional[FormDocument]:
        return await FormDocument.find_one(
            FormDocument.documentType == document_type,
            FormDocument.contentLink == content_link,
        )

    async def list_forms(
        self,
        skip: int = 0,
        limit: int = 100,
        search: Optional[str] = None,
    ) -> Tuple[List[FormDocument], int]:
        q_args = []
        if search:
            q_args.append({"documentType": {"$regex": search, "$options": "i"}})

        query = FormDocument.find(*q_args)
        total = await query.count()
        items = await query.sort("-created_at").skip(skip).limit(limit).to_list()
        return items, total
