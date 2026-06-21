import logging
import asyncio
from typing import List, Dict, Any, Optional

from app.modules.forms.repositories.form_repository import FormRepository
from app.modules.forms.models.form import FormDocument
from app.core.pagination import PagedResult

logger = logging.getLogger(__name__)

_form_service_instance: Optional['FormService'] = None
_form_service_lock = asyncio.Lock()

class FormService:
    def __init__(self):
        self._repo = FormRepository()

    async def create_form(self, document_type: str, content_link: str, notes: Optional[str] = None):
        doc = FormDocument(documentType=document_type, contentLink=content_link, notes=notes)
        return await self._repo.create(doc)

    async def get_form_by_id(self, form_id: str):
        return await self._repo.find_by_id(form_id)

    async def update_form(self, form_id: str, document_type: Optional[str] = None, content_link: Optional[str] = None, notes: Optional[str] = None):
        doc = await self._repo.find_by_id(form_id)
        if not doc:
            return None

        changed = False
        if document_type is not None:
            doc.documentType = document_type
            changed = True
        if content_link is not None:
            doc.contentLink = content_link
            changed = True
        if notes is not None:
            doc.notes = notes
            changed = True

        if not changed:
            return doc
        return await self._repo.save(doc)

    async def delete_form(self, form_id: str) -> bool:
        doc = await self._repo.find_by_id(form_id)
        if not doc:
            return False
        await self._repo.delete(doc)
        return True

    async def list_forms(self, page: int = 1, limit: int = 20, search: Optional[str] = None) -> PagedResult[FormDocument]:
        items, total = await self._repo.list_forms(skip=(page - 1) * limit, limit=limit, search=search)
        return PagedResult(items=items, total=total, page=page, limit=limit)

    async def upsert_many(self, items: List[Dict[str, Any]]) -> int:
        count = 0
        for item in items:
            existing = await self._repo.find_by_document_type(item["document_type"])
            if existing:
                form_id = str(existing.id)
                await self.update_form(
                    form_id,
                    content_link=item.get("content_link"),
                    notes=item.get("notes")
                )
                count += 1
            else:
                await self.create_form(
                    document_type=item["document_type"],
                    content_link=item["content_link"],
                    notes=item.get("notes")
                )
                count += 1
        return count

async def get_form_service() -> FormService:
    global _form_service_instance, _form_service_lock
    if _form_service_instance is None:
        async with _form_service_lock:
            if _form_service_instance is None:
                _form_service_instance = FormService()
    return _form_service_instance
