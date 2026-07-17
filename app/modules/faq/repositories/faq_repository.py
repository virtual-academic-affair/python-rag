from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, List, Optional, Tuple

from bson import ObjectId

from app.core.base_beanie_repository import BeanieRepository
from app.modules.faq.models.faq import FaqDocument

logger = logging.getLogger(__name__)


class FaqRepository(BeanieRepository[FaqDocument]):
    """Repository-specific queries for FAQ documents."""

    document_class = FaqDocument

    @staticmethod
    def _active_query(filters: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        if not filters:
            return {"deleted_at": None}
        return {"$and": [{"deleted_at": None}, filters]}

    @staticmethod
    def _deleted_query(filters: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        deleted = {"deleted_at": {"$type": "date"}}
        if not filters:
            return deleted
        return {"$and": [deleted, filters]}

    async def find_by_id(self, doc_id: str) -> Optional[FaqDocument]:
        if not ObjectId.is_valid(str(doc_id)):
            return None
        return await FaqDocument.find_one({"_id": ObjectId(doc_id), "deleted_at": None})

    async def find_by_id_including_deleted(self, doc_id: str) -> Optional[FaqDocument]:
        return await super().find_by_id(doc_id)

    async def find_by_unaccented_question(self, question_unaccented: str) -> Optional[FaqDocument]:
        return await FaqDocument.find_one({
            "question_unaccented": question_unaccented,
            "deleted_at": None,
        })

    async def list_faqs(
        self,
        metadata_filter: Optional[dict[str, Any]] = None,
        search_text: Optional[str] = None,
        skip: int = 0,
        limit: int = 20,
    ) -> Tuple[List[FaqDocument], int]:
        query = FaqDocument.find(self._active_query(metadata_filter))

        if search_text:
            query = query.find({"$text": {"$search": search_text}}).sort(
                [("score", {"$meta": "textScore"})]
            )
        else:
            query = query.sort("-created_at")

        total = await query.count()
        items = await query.skip(skip).limit(limit).to_list()
        return items, total

    async def list_deleted_faqs(
        self,
        metadata_filter: Optional[dict[str, Any]] = None,
        search_text: Optional[str] = None,
        skip: int = 0,
        limit: int = 20,
    ) -> Tuple[List[FaqDocument], int]:
        query = FaqDocument.find(self._deleted_query(metadata_filter))
        if search_text:
            query = query.find({"$text": {"$search": search_text}}).sort(
                [("score", {"$meta": "textScore"})]
            )
        else:
            query = query.sort("-deleted_at")
        total = await query.count()
        items = await query.skip(skip).limit(limit).to_list()
        return items, total

    async def list_active(self, skip: int = 0, limit: int = 100) -> List[FaqDocument]:
        return (
            await FaqDocument.find({"deleted_at": None})
            .sort("-created_at")
            .skip(skip)
            .limit(limit)
            .to_list()
        )

    async def increment_view_count(self, faq_id: str) -> bool:
        try:
            doc = await self.find_by_id(faq_id)
            if not doc:
                return False
            await doc.update({"$inc": {"view_count": 1}})
            return True
        except Exception as e:
            logger.error(f"[FAQ] Failed to increment view count for FAQ {faq_id}: {e}")
            return False

    async def find_by_ids(self, faq_ids: List[str]) -> List[FaqDocument]:
        if not faq_ids:
            return []
        object_ids = []
        for fid in faq_ids:
            try:
                object_ids.append(ObjectId(fid))
            except Exception:
                continue
        if not object_ids:
            return []
        return await FaqDocument.find(self._active_query({"_id": {"$in": object_ids}})).to_list()

    async def find_ids_by_query(self, query: dict[str, Any]) -> set[str]:
        ids: set[str] = set()
        cursor = FaqDocument.get_motor_collection().find(self._active_query(query), {"_id": 1})
        async for row in cursor:
            ids.add(str(row["_id"]))
        return ids

    async def soft_delete(self, faq_id: str, *, deleted_by: str, corpus_node_keys: List[str]) -> bool:
        if not ObjectId.is_valid(str(faq_id)):
            return False
        now = datetime.now(timezone.utc)
        result = await FaqDocument.get_motor_collection().update_one(
            {"_id": ObjectId(faq_id), "deleted_at": None},
            {
                "$set": {
                    "deleted_at": now,
                    "deleted_by": deleted_by,
                    "deleted_corpus_node_keys": list(dict.fromkeys(corpus_node_keys)),
                    "updated_at": now,
                }
            },
        )
        return result.modified_count == 1

    async def restore(self, faq_id: str) -> bool:
        if not ObjectId.is_valid(str(faq_id)):
            return False
        now = datetime.now(timezone.utc)
        result = await FaqDocument.get_motor_collection().update_one(
            {"_id": ObjectId(faq_id), "deleted_at": {"$type": "date"}},
            {
                "$set": {
                    "deleted_at": None,
                    "deleted_by": None,
                    "deleted_corpus_node_keys": [],
                    "updated_at": now,
                }
            },
        )
        return result.modified_count == 1
