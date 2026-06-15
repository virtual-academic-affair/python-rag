from typing import List, Optional, Dict, Any
from app.core.base_repository import BaseRepository
from app.modules.faq.models.faq import FaqDocument

class FaqRepository(BaseRepository):
    """Repository for FAQs using Beanie ODM."""
    
    def __init__(self):
        super().__init__("faqs")
        
    def _serialize_doc(self, doc) -> Optional[Dict[str, Any]]:
        if not doc:
            return None
        if isinstance(doc, dict):
            d = doc.copy()
            if "_id" in d:
                d["_id"] = str(d["_id"])
            return d
        d = doc.model_dump(by_alias=True)
        d["_id"] = str(doc.id)
        return d

    async def find_active(self, skip: int = 0, limit: int = 100) -> List[Dict[str, Any]]:
        docs = await FaqDocument.find(
            {"is_active": True},
            skip=skip,
            limit=limit,
            sort=[("created_at", -1)]
        ).to_list()
        return [self._serialize_doc(d) for d in docs]

    async def find_by_qdrant_point_id(self, point_id: str) -> Optional[Dict[str, Any]]:
        doc = await FaqDocument.find_one({"qdrant_point_id": point_id})
        return self._serialize_doc(doc)

    async def increment_view_count(self, faq_id: str) -> bool:
        doc = await FaqDocument.get(faq_id)
        if doc:
            doc.view_count += 1
            await doc.save()
            return True
        return False
