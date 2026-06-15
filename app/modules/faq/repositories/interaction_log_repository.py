import logging
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone, timedelta
from bson import ObjectId
from app.core.base_repository import BaseRepository
from app.core.config import settings
from app.modules.faq.models.interaction_log import InteractionLogDocument
from app.utils.text_utils import remove_accents

logger = logging.getLogger(__name__)

class InteractionLogRepository(BaseRepository):
    """Repository for Interaction Logs using Beanie ODM."""
    
    def __init__(self):
        super().__init__("interaction_logs")
        
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

        cutoff_id = ObjectId.from_datetime(now - timedelta(hours=24))

        # Deduplicate based on exact unaccented question in the last 24h
        existing = await InteractionLogDocument.find_one({
            "question_unaccented": question_unaccented,
            "_id": {"$gt": cutoff_id}
        })
        if existing:
            return doc

        await doc.insert()
        return doc

    async def find_for_synthesis(
        self,
        date_from: datetime,
        date_to: datetime,
        source_types: List[str]
    ) -> List[Dict[str, Any]]:
        dummy_id_from = ObjectId.from_datetime(date_from)
        dummy_id_to = ObjectId.from_datetime(date_to)

        docs = await InteractionLogDocument.find(
            {
                "_id": {"$gte": dummy_id_from, "$lte": dummy_id_to},
                "source_type": {"$in": source_types}
            },
            limit=10000,
            sort=[("_id", 1)]
        ).to_list()
        
        if len(docs) == 10000:
            logger.warning("Synthesis log query hit the maximum limit of 10000. Some interactions might be skipped.")
            
        return [self._serialize_doc(d) for d in docs]
