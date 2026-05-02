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
                    "metadata_filter.academic_year",
                    "metadata_filter.cohort"
                ]
                for field in fields:
                    try:
                        self.qdrant_client_instance.create_payload_index(
                            collection_name=settings.FAQ_QDRANT_COLLECTION,
                            field_name=field,
                            field_schema=qm.PayloadSchemaType.KEYWORD,
                        )
                    except Exception:
                        pass

            await asyncio.to_thread(_ensure)
            _faq_collection_ready = True

    def _stable_point_id(self, faq_id: str) -> str:
        """Qdrant accepts UUID or unsigned integer. Using a uuid format derived from faq_id."""
        h = hashlib.md5(faq_id.encode("utf-8")).hexdigest()
        return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"

    async def upsert_faq(self, faq_id: str, question_vector: List[float], metadata_filter: Dict[str, List[str]]) -> str:
        """
        Upsert a single FAQ into Qdrant.
        
        Args:
            faq_id: The string ID of the FAQ in MongoDB.
            question_vector: The embedded question.
            metadata_filter: The dictionary of metadata filters.
            
        Returns:
            The generated Qdrant point ID.
        """
        await self.ensure_collection()
        point_id = self._stable_point_id(faq_id)
        
        payload = {
            "faq_id": faq_id,
            "metadata_filter": metadata_filter
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
        """Convert a dictionary to Qdrant Filter."""
        if not metadata_filter_dict:
            return None
            
        must_conditions = []
        for key, values in metadata_filter_dict.items():
            if values and isinstance(values, list):
                # If a filter is provided, the FAQ must match at least one of the values,
                # OR the FAQ must not specify any filter for this key (empty array means applies to all).
                # But since we store empty array when it applies to all, we need to check both.
                
                # However, for simplicity and typical RAG pattern, we can just do a direct match.
                # If the FAQ has `academic_year: ["2024-2025"]`, and query has `academic_year: ["2024-2025"]`, it matches.
                # If the FAQ has `academic_year: []`, it should match any query.
                
                # To implement: FAQ applies if (FAQ.key is empty) OR (FAQ.key intersects with Query.key)
                # Qdrant condition:
                condition = qm.Filter(
                    should=[
                        qm.FieldCondition(
                            key=f"metadata_filter.{key}",
                            match=qm.MatchAny(any=values)
                        ),
                        qm.IsEmptyCondition(
                            is_empty=qm.PayloadField(key=f"metadata_filter.{key}")
                        )
                    ]
                )
                must_conditions.append(condition)
                
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
