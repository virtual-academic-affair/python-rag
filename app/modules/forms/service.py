import logging
import asyncio
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone

from app.modules.forms.repository import FormRepository
from app.modules.forms.excel_parser import parse_excel_to_form_rows
from app.core.exceptions import DatabaseException

logger = logging.getLogger(__name__)

_form_service_instance: Optional['FormService'] = None
_form_service_lock = asyncio.Lock()

class FormService:
    def __init__(self):
        self._repo = FormRepository()

    async def create_form(self, document_type: str, content_link: str, notes: Optional[str] = None) -> Dict[str, Any]:
        doc_dict = {
            "documentType": document_type,
            "contentLink": content_link,
            "notes": notes,
            "createdAt": datetime.now(timezone.utc),
            "updatedAt": datetime.now(timezone.utc)
        }
        return await self._repo.create(doc_dict)

    async def get_form_by_id(self, form_id: str) -> Optional[Dict[str, Any]]:
        return await self._repo.find_by_id(form_id)

    async def update_form(self, form_id: str, document_type: Optional[str] = None, content_link: Optional[str] = None, notes: Optional[str] = None) -> Optional[Dict[str, Any]]:
        update_data = {"updatedAt": datetime.now(timezone.utc)}
        if document_type is not None: update_data["documentType"] = document_type
        if content_link is not None: update_data["contentLink"] = content_link
        if notes is not None: update_data["notes"] = notes

        if len(update_data) == 1: return await self.get_form_by_id(form_id)
        await self._repo.update_by_id(form_id, update_data)
        return await self.get_form_by_id(form_id)

    async def delete_form(self, form_id: str) -> bool:
        return await self._repo.delete_by_id(form_id)

    async def list_forms(self, page: int = 1, limit: int = 20, search: Optional[str] = None) -> Dict[str, Any]:
        skip = (page - 1) * limit
        items = await self._repo.find_all_forms(skip=skip, limit=limit, search=search)
        total = await self._repo.count_forms(search=search)
        return {
            "items": items,
            "total": total,
            "page": page,
            "limit": limit
        }

    async def upsert_many(self, items: List[Dict[str, Any]]) -> int:
        count = 0
        for item in items:
            # Find existing record by document_type only (Nội dung)
            existing = await self._repo.find_one({
                "documentType": item["document_type"]
            })
            if existing:
                await self.update_form(
                    str(existing["_id"]),
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
