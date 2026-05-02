"""
Repositories for the FAQ Module.
"""
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone, timedelta
from pymongo import ASCENDING, DESCENDING

from app.repositories.base import BaseRepository
from app.core.database import Database
from app.core.config import settings
from app.modules.faq.models import FaqDocument, FaqCandidateDocument, InteractionLogDocument
from app.core.text_utils import remove_accents



class FaqRepository(BaseRepository):
    def __init__(self):
        super().__init__(Database.FAQS)

    async def find_active(self, skip: int = 0, limit: int = 100) -> List[Dict[str, Any]]:
        return await self.find_many(
            query={"is_active": True},
            skip=skip,
            limit=limit,
            sort=[("created_at", DESCENDING)]
        )

    async def find_by_qdrant_point_id(self, point_id: str) -> Optional[Dict[str, Any]]:
        return await self.find_one({"qdrant_point_id": point_id})

    async def increment_view_count(self, faq_id: str) -> bool:
        from bson import ObjectId
        result = await self.collection.update_one(
            {"_id": ObjectId(faq_id) if isinstance(faq_id, str) else faq_id},
            {"$inc": {"view_count": 1}}
        )
        return result.modified_count > 0


class FaqCandidateRepository(BaseRepository):
    def __init__(self):
        super().__init__(Database.FAQ_CANDIDATES)

    async def find_by_status(self, status: Optional[str] = None, skip: int = 0, limit: int = 100) -> List[Dict[str, Any]]:
        query = {}
        if status:
            query["status"] = status
            
        return await self.find_many(
            query=query,
            skip=skip,
            limit=limit,
            sort=[("created_at", ASCENDING)]
        )


class InteractionLogRepository(BaseRepository):
    def __init__(self):
        super().__init__(Database.INTERACTION_LOGS)

    async def log(
        self,
        question: str,
        answer_markdown: str,
        question_vector: Optional[List[float]] = None,
        metadata_filter: Optional[Dict[str, Any]] = None,
        source_type: str = "chat",
        email_message_id: Optional[int] = None,
        processing_time_ms: int = 0
    ) -> InteractionLogDocument:
        """Log an interaction to the database."""
        # Unaccent question for future deduplication/synthesis
        question_unaccented = remove_accents(question)
        
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(days=settings.FAQ_LOG_RETENTION_DAYS)

        doc = InteractionLogDocument(
            question=question,
            question_unaccented=question_unaccented,
            answer_markdown=answer_markdown,
            question_vector=question_vector,
            metadata_filter=metadata_filter or {},
            source_type=source_type,
            email_message_id=email_message_id,
            processing_time_ms=processing_time_ms,
            expires_at=expires_at
        )
        
        if not question or len(question.strip()) < settings.FAQ_LOG_MIN_QUESTION_LENGTH:
            return doc

        from bson import ObjectId
        cutoff_id = ObjectId.from_datetime(now - timedelta(hours=24))

        # Deduplicate based on exact unaccented question in the last 24h
        existing = await self.find_one({
            "question_unaccented": question_unaccented,
            "_id": {"$gt": cutoff_id}
        })
        if existing:
            return

        await self.create({
            "question": question,
            "question_unaccented": question_unaccented,
            "question_vector": question_vector,
            "answer_markdown": answer_markdown,
            "metadata_filter": metadata_filter,
            "source_type": source_type,
            "processing_time_ms": processing_time_ms,
            "email_message_id": email_message_id,
            "expires_at": expires_at,
        })

    async def find_for_synthesis(self, date_from: datetime, date_to: datetime, source_types: List[str]) -> List[Dict[str, Any]]:
        from bson import ObjectId
        # MongoDB ObjectIds encode the creation timestamp. We can query by _id range.
        # Alternatively, we could add created_at, but we decided to use _id for simplicity.
        # Since _id contains timestamp, we can generate dummy ObjectIds for bounds.
        
        # Generation of ObjectId from datetime
        dummy_id_from = ObjectId.from_datetime(date_from)
        dummy_id_to = ObjectId.from_datetime(date_to)

        results = await self.find_many(
            query={
                "_id": {"$gte": dummy_id_from, "$lte": dummy_id_to},
                "source_type": {"$in": source_types}
            },
            limit=10000, # Cap at a reasonable number for processing
            sort=[("_id", ASCENDING)]
        )
        
        if len(results) == 10000:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning("Synthesis log query hit the maximum limit of 10000. Some interactions might be skipped.")
            
        return results
