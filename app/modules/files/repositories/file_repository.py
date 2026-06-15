from typing import List, Optional
from bson import ObjectId
from app.core.base_repository import BaseRepository
from app.modules.files.models.file import FileDocument, FileStatus

class FileRepository(BaseRepository):
    """Repository for file documents using Beanie ODM."""
    
    def __init__(self):
        super().__init__("files")
    
    async def update_status(
        self,
        file_id: str,
        status: FileStatus,
    ) -> bool:
        doc = await FileDocument.get(file_id)
        if doc:
            doc.status = status
            await doc.save()
            return True
        return False
    
    async def find_by_display_names(self, display_names: List[str]) -> List[dict]:
        if not display_names:
            return []
        docs = await FileDocument.find(
            {"display_name": {"$in": display_names}}
        ).to_list()
        # Callers expect raw dict format
        results = []
        for doc in docs:
            d = doc.model_dump(by_alias=True)
            d["_id"] = str(doc.id)
            results.append(d)
        return results

    async def find_by_ids(self, file_ids: List[str]) -> List[dict]:
        if not file_ids:
            return []
            
        object_ids = []
        for fid in file_ids:
            try:
                object_ids.append(ObjectId(fid))
            except Exception:
                continue
                
        if not object_ids:
            return []
            
        docs = await FileDocument.find(
            {"_id": {"$in": object_ids}}
        ).to_list()
        
        results = []
        for doc in docs:
            d = doc.model_dump(by_alias=True)
            d["_id"] = str(doc.id)
            results.append(d)
        return results
