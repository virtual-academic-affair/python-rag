from typing import List, Optional, Dict, Any
from app.core.base_repository import BaseRepository
from app.modules.faq.models.faq_candidate import FaqCandidateDocument

class FaqCandidateRepository(BaseRepository):
    """Repository for FAQ Candidates using Beanie ODM."""
    
    def __init__(self):
        super().__init__("faq_candidates")
        
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

    async def find_by_status(
        self,
        status: Optional[str] = None,
        skip: int = 0,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        query = {}
        if status:
            query["status"] = status
            
        docs = await FaqCandidateDocument.find(
            query,
            skip=skip,
            limit=limit,
            sort=[("created_at", 1)]
        ).to_list()
        return [self._serialize_doc(d) for d in docs]
