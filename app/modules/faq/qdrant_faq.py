"""
Qdrant service specifically for the FAQ module.
Manages the 'faqs' collection independently of the main document retrieval collection.
"""
import asyncio
import hashlib
from typing import Any, Optional, List, Dict
import logging

from qdrant_client import QdrantClient
from qdrant_client import models as qm
from google import genai
from google.genai import types

from app.core.config import settings
from app.integrations.llm.embedding import get_embedding_service

logger = logging.getLogger(__name__)

_qdrant_faq_service_instance: Optional['QdrantFaqService'] = None
_faq_collection_ready: bool = False
_faq_qdrant_lock = asyncio.Lock()


class QdrantFaqService:
    def __init__(self):
        self._client: Optional[QdrantClient] = None

    async def embed_question(self, text: str) -> List[float]:
        """Generate embedding vector for a question using shared EmbeddingService."""
        return await get_embedding_service().embed(text)

    @property
    def qdrant_client_instance(self) -> QdrantClient:
        if self._client is None:
            self._client = QdrantClient(
                url=settings.QDRANT_URL,
                api_key=settings.QDRANT_API_KEY or None,
                timeout=30,
            )
        return self._client

    async def ensure_collection(self) -> None:
        """Ensure the 'faqs' collection and indexes exist (only once per process)."""
        global _faq_collection_ready
        if _faq_collection_ready:
            return

        async with _faq_qdrant_lock:
            if _faq_collection_ready:
                return

            def _ensure() -> None:
                collections = self.qdrant_client_instance.get_collections().collections
                names = {c.name for c in collections}
                if settings.FAQ_QDRANT_COLLECTION not in names:
                    self.qdrant_client_instance.create_collection(
                        collection_name=settings.FAQ_QDRANT_COLLECTION,
                        vectors_config=qm.VectorParams(
                            size=settings.QDRANT_VECTOR_SIZE,
                            distance=qm.Distance.COSINE,
                        ),
                    )
                    logger.info(f"Created Qdrant collection: {settings.FAQ_QDRANT_COLLECTION}")

                # Ensure payload indexes
                fields = [
                    ("metadata_filter.enrollment_year_from", qm.PayloadSchemaType.INTEGER),
                    ("metadata_filter.enrollment_year_to",   qm.PayloadSchemaType.INTEGER),
                    ("metadata_filter.academic_year_from",   qm.PayloadSchemaType.INTEGER),
                    ("metadata_filter.academic_year_to",     qm.PayloadSchemaType.INTEGER),
                    ("metadata_filter.type",                 qm.PayloadSchemaType.KEYWORD),
                ]
                for field, schema_type in fields:
                    try:
                        self.qdrant_client_instance.create_payload_index(
                            collection_name=settings.FAQ_QDRANT_COLLECTION,
                            field_name=field,
                            field_schema=schema_type,
                        )
                    except Exception:
                        pass

            await asyncio.to_thread(_ensure)
            _faq_collection_ready = True

    def _stable_point_id(self, faq_id: str) -> str:
        """Qdrant accepts UUID or unsigned integer. Using a uuid format derived from faq_id."""
        h = hashlib.md5(faq_id.encode("utf-8")).hexdigest()
        return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"

    async def upsert_faq(self, faq_id: str, question_vector: List[float], metadata_filter: Dict[str, Any]) -> str:
        """
        Upsert a single FAQ into Qdrant.
        """
        await self.ensure_collection()
        point_id = self._stable_point_id(faq_id)
        
        from app.modules.metadata.service import get_metadata_service
        try:
            # Always normalize through schema for consistent Qdrant payload
            _, _, meta_model = get_metadata_service().validate_and_parse_faq_metadata(metadata_filter)
            if meta_model:
                flat_meta = meta_model.to_qdrant_payload()
            else:
                flat_meta = {}
        except Exception as e:
            logger.warning(f"Failed to parse FAQ metadata for Qdrant upsert: {e}")
            flat_meta = {}

        payload = {
            "faq_id": faq_id,
            "metadata_filter": flat_meta
        }
        
        point = qm.PointStruct(
            id=point_id,
            vector=question_vector,
            payload=payload
        )
        
        await asyncio.to_thread(
            self.qdrant_client_instance.upsert,
            collection_name=settings.FAQ_QDRANT_COLLECTION,
            points=[point],
            wait=True,
        )
        return point_id

    async def delete_faq(self, qdrant_point_id: str) -> None:
        """Delete an FAQ from Qdrant by point ID."""
        await self.ensure_collection()
        await asyncio.to_thread(
            self.qdrant_client_instance.delete,
            collection_name=settings.FAQ_QDRANT_COLLECTION,
            points_selector=qm.PointIdsList(points=[qdrant_point_id]),
            wait=True,
        )

    def _build_filter(self, metadata_filter_dict: Dict[str, Any]) -> Optional[qm.Filter]:
        """Convert an InquiryFilters/FaqMetadata dict to Qdrant Filter."""
        if not metadata_filter_dict:
            return None

        # Strip None values trước — tránh Pydantic V2 từ chối khi field là non-optional YearRange
        clean_dict = {k: v for k, v in metadata_filter_dict.items() if v is not None}
        if not clean_dict:
            return None

        from app.modules.metadata.schemas import FaqMetadataSchema
        from app.modules.metadata.models import YEAR_MIN, YEAR_MAX
        try:
            schema = FaqMetadataSchema.model_validate(clean_dict)
            model = schema.to_model()
        except Exception as e:
            logger.warning(f"Invalid FAQ metadata filter: {e}")
            return None

        must_conditions = []

        # 1. Enrollment year
        if model.enrollment_year:
            f = model.enrollment_year.from_year
            t = model.enrollment_year.to_year
            if f != YEAR_MIN or t != YEAR_MAX:
                must_conditions.extend([
                    qm.FieldCondition(key="metadata_filter.enrollment_year_to", range=qm.Range(gte=f)),
                    qm.FieldCondition(key="metadata_filter.enrollment_year_from", range=qm.Range(lte=t))
                ])

        # 2. Academic year
        if model.academic_year:
            af = model.academic_year.from_year
            at = model.academic_year.to_year
            if af != YEAR_MIN or at != YEAR_MAX:
                must_conditions.extend([
                    qm.FieldCondition(key="metadata_filter.academic_year_to", range=qm.Range(gte=af)),
                    qm.FieldCondition(key="metadata_filter.academic_year_from", range=qm.Range(lte=at))
                ])

        # 3. Type
        model_type = getattr(model, "type", None)
        if model_type:
            # FAQ can apply to all types if it has no type (type="")
            must_conditions.append(
                qm.Filter(
                    should=[
                        qm.FieldCondition(key="metadata_filter.type", match=qm.MatchValue(value=model_type.value)),
                        qm.FieldCondition(key="metadata_filter.type", match=qm.MatchValue(value=""))
                    ]
                )
            )

        if not must_conditions:
            return None
            
        return qm.Filter(must=must_conditions)

    async def search(self, query_vector: List[float], metadata_filter_dict: Dict[str, Any], threshold: float, top_k: int = 1) -> List[Dict[str, Any]]:
        """
        Search for the best FAQ match.
        """
        await self.ensure_collection()
        
        qdrant_filter = self._build_filter(metadata_filter_dict)
        
        query_response = await asyncio.to_thread(
            self.qdrant_client_instance.query_points,
            collection_name=settings.FAQ_QDRANT_COLLECTION,
            query=query_vector,
            query_filter=qdrant_filter,
            limit=top_k,
            score_threshold=threshold,
            with_payload=True,
        )
        
        results = []
        for res in query_response.points:
            payload = res.payload or {}
            results.append({
                "faq_id": payload.get("faq_id"),
                "score": res.score
            })
            
        return results


async def get_qdrant_faq_service() -> QdrantFaqService:
    global _qdrant_faq_service_instance
    if _qdrant_faq_service_instance is None:
        async with _faq_qdrant_lock:
            if _qdrant_faq_service_instance is None:
                _qdrant_faq_service_instance = QdrantFaqService()
    return _qdrant_faq_service_instance
