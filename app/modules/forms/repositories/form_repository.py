from typing import List, Optional
from app.modules.forms.models.form import FormDocument

class FormRepository:
    async def create(self, doc_dict: dict) -> FormDocument:
        doc = FormDocument(
            documentType=doc_dict.get("documentType"),
            contentLink=doc_dict.get("contentLink"),
            notes=doc_dict.get("notes")
        )
        await doc.insert()
        return doc

    async def find_by_id(self, form_id: str) -> Optional[FormDocument]:
        try:
            return await FormDocument.get(form_id)
        except Exception:
            return None

    async def find_one(self, query: dict) -> Optional[FormDocument]:
        q_args = []
        if "documentType" in query:
            q_args.append(FormDocument.documentType == query["documentType"])
        if "contentLink" in query:
            q_args.append(FormDocument.contentLink == query["contentLink"])
        
        return await FormDocument.find_one(*q_args)

    async def update_by_id(self, form_id: str, update_data: dict) -> Optional[FormDocument]:
        doc = await self.find_by_id(form_id)
        if not doc:
            return None
        
        if "documentType" in update_data:
            doc.documentType = update_data["documentType"]
        if "contentLink" in update_data:
            doc.contentLink = update_data["contentLink"]
        if "notes" in update_data:
            doc.notes = update_data["notes"]
            
        await doc.save()
        return doc

    async def delete_by_id(self, form_id: str) -> bool:
        doc = await self.find_by_id(form_id)
        if not doc:
            return False
        await doc.delete()
        return True

    async def find_all_forms(self, skip: int = 0, limit: int = 100, search: Optional[str] = None) -> List[FormDocument]:
        q_args = []
        if search:
            q_args.append(FormDocument.documentType == {"$regex": search, "$options": "i"})
        
        # In Beanie, created_at corresponds to createdAt alias
        return await FormDocument.find(*q_args).sort("-created_at").skip(skip).limit(limit).to_list()

    async def count_forms(self, search: Optional[str] = None) -> int:
        q_args = []
        if search:
            q_args.append(FormDocument.documentType == {"$regex": search, "$options": "i"})
        return await FormDocument.find(*q_args).count()

    async def find_one_by_content_link(self, document_type: str, content_link: str) -> Optional[FormDocument]:
        return await FormDocument.find_one(
            FormDocument.documentType == document_type,
            FormDocument.contentLink == content_link
        )
