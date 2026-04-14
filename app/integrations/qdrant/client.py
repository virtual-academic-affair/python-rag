"""
Qdrant retrieval service for semantic search.
"""

from __future__ import annotations

import asyncio
import hashlib
from typing import Any, Optional, List

from qdrant_client import QdrantClient
from qdrant_client import models as qm
from google import genai

from app.core.config import settings
import logging

logger = logging.getLogger(__name__)

_qdrant_retrieval_service_instance: Optional[QdrantRetrievalService] = None
_collection_ready: bool = False

class QdrantRetrievalService:
    def __init__(self):
        self._client: Optional[QdrantClient] = None
        self._genai_client = genai.Client(api_key=settings.GOOGLE_API_KEY)
        self._embed_model_name = "models/gemini-embedding-001" # User specified embedding model

    @property
    def qdrant_client_instance(self) -> QdrantClient:
        if self._client is None:
            self._client = QdrantClient(
                url=settings.QDRANT_URL,
                api_key=settings.QDRANT_API_KEY or None,
                timeout=30,
            )
        return self._client

    async def _get_embedding(self, text: str) -> List[float]:
        """Get embedding using new google-genai SDK (native async)."""
        from google.genai import types
        response = await self._genai_client.aio.models.embed_content(
            model=self._embed_model_name,
            contents=text,
            config=types.EmbedContentConfig(output_dimensionality=settings.QDRANT_VECTOR_SIZE)
        )
        return response.embeddings[0].values

    async def ensure_collection(self) -> None:
        """Ensure collection and indexes exist (only once per process)."""
        global _collection_ready
        if _collection_ready:
            return

        def _ensure() -> None:
            collections = self.qdrant_client_instance.get_collections().collections
            names = {c.name for c in collections}
            if settings.QDRANT_COLLECTION_NAME not in names:
                self.qdrant_client_instance.create_collection(
                    collection_name=settings.QDRANT_COLLECTION_NAME,
                    vectors_config=qm.VectorParams(
                        size=settings.QDRANT_VECTOR_SIZE,
                        distance=qm.Distance.COSINE,
                    ),
                )
            
            # Ensure payload indexes
            fields = [
                "file_id", 
                "metadata.access_scope", 
                "metadata.academic_year", 
                "metadata.department"
            ]
            for field in fields:
                try:
                    self.qdrant_client_instance.create_payload_index(
                        collection_name=settings.QDRANT_COLLECTION_NAME,
                        field_name=field,
                        field_schema=qm.PayloadSchemaType.KEYWORD,
                    )
                except Exception:
                    pass

        await asyncio.to_thread(_ensure)
        _collection_ready = True

    async def retrieve(
        self,
        query: str,
        top_k: Optional[int] = None,
        min_score: Optional[float] = None,
        metadata_filter: Optional[qm.Filter] = None,
    ) -> list[dict[str, Any]]:
        """Perform semantic vector search in Qdrant."""
        await self.ensure_collection()
        k = max(1, int(top_k or settings.QDRANT_TOP_K))
        
        # 1. Generate query embedding with new SDK
        query_vector = await self._get_embedding(query)
        
        query_response = await asyncio.to_thread(
            self.qdrant_client_instance.query_points,
            collection_name=settings.QDRANT_COLLECTION_NAME,
            query=query_vector,
            query_filter=metadata_filter,
            limit=k,
            score_threshold=min_score or settings.QDRANT_MIN_SCORE,
            with_payload=True,
        )

        docs: list[dict[str, Any]] = []
        for res in query_response.points:
            payload = res.payload or {}
            docs.append(
                {
                    "file_id": payload.get("file_id"),
                    "file_name": payload.get("file_name"),
                    "text": payload.get("text") or "",
                    "section_path": payload.get("section_path"),
                    "metadata": payload.get("metadata") or {},
                    "_retrieval_score": res.score,
                }
            )
        return docs

    @staticmethod
    def _stable_point_id(file_id: str) -> int:
        h = hashlib.sha1(file_id.encode("utf-8", errors="ignore")).hexdigest()[:16]
        return int(h, 16) % (2**63 - 1)


def get_qdrant_retrieval_service() -> QdrantRetrievalService:
    global _qdrant_retrieval_service_instance
    if _qdrant_retrieval_service_instance is None:
        _qdrant_retrieval_service_instance = QdrantRetrievalService()
    return _qdrant_retrieval_service_instance
