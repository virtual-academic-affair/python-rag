"""
Qdrant retrieval service for semantic search.
"""

from __future__ import annotations

import asyncio
import hashlib
from typing import Any, Optional

from qdrant_client import QdrantClient
from qdrant_client import models as qm

from app.core.config import settings



class QdrantRetrievalService:
    def __init__(self):
        self._client: Optional[QdrantClient] = None

    @property
    def client(self) -> QdrantClient:
        if self._client is None:
            self._client = QdrantClient(
                url=settings.QDRANT_URL,
                api_key=settings.QDRANT_API_KEY or None,
                timeout=30,
            )
        return self._client

    async def ensure_collection(self) -> None:
        def _ensure() -> None:
            collections = self.client.get_collections().collections
            names = {c.name for c in collections}
            if settings.QDRANT_COLLECTION_NAME in names:
                return
            self.client.create_collection(
                collection_name=settings.QDRANT_COLLECTION_NAME,
                vectors_config=qm.VectorParams(
                    size=settings.QDRANT_VECTOR_SIZE,
                    distance=qm.Distance.COSINE,
                ),
            )

        await asyncio.to_thread(_ensure)

    async def upsert_file_overview(
        self,
        *,
        file_id: str,
        file_name: str,
        summary: str,
        table_of_contents: list[str],
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        await self.ensure_collection()
        vector = [0.0] * settings.QDRANT_VECTOR_SIZE
        payload = {
            "file_id": file_id,
            "file_name": file_name,
            "summary": summary,
            "table_of_contents": table_of_contents,
            "metadata": metadata or {},
            "section_path": "overview",
            "page_index_start": None,
            "page_index_end": None,
            "text": "",
        }

        point = qm.PointStruct(
            id=self._stable_point_id(file_id),
            vector=vector,
            payload=payload,
        )

        await asyncio.to_thread(
            self.client.upsert,
            collection_name=settings.QDRANT_COLLECTION_NAME,
            points=[point],
            wait=True,
        )

    async def retrieve(
        self,
        query: str,
        top_k: Optional[int] = None,
        min_score: Optional[float] = None,
        metadata_filter: Optional[dict[str, Any]] = None,
        user_role: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        await self.ensure_collection()
        k = max(1, int(top_k or settings.QDRANT_TOP_K))
        flt = self._build_filter(metadata_filter=metadata_filter, user_role=user_role)

        points, _ = await asyncio.to_thread(
            self.client.scroll,
            collection_name=settings.QDRANT_COLLECTION_NAME,
            scroll_filter=flt,
            limit=k,
            with_payload=True,
            with_vectors=False,
        )

        docs: list[dict[str, Any]] = []
        for p in points:
            payload = p.payload or {}
            docs.append(
                {
                    "file_id": payload.get("file_id"),
                    "file_name": payload.get("file_name"),
                    "text": payload.get("summary") or "",
                    "summary": payload.get("summary") or "",
                    "table_of_contents": payload.get("table_of_contents") or [],
                    "section_path": payload.get("section_path") or "overview",
                    "page_index_start": payload.get("page_index_start"),
                    "page_index_end": payload.get("page_index_end"),
                    "metadata": payload.get("metadata") or {},
                    "_retrieval_score": None,
                    "_retrieval_explain": {"mode": "payload_only_no_embedding", "query": query},
                }
            )
        return docs

    def get_cache_stats(self) -> dict[str, Any]:
        return {
            "cache_size": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "cache_hit_rate": 0.0,
            "ttl_seconds": 0,
            "max_keys": 0,
        }



    @staticmethod
    def _stable_point_id(file_id: str) -> int:
        h = hashlib.sha1(file_id.encode("utf-8", errors="ignore")).hexdigest()[:16]
        return int(h, 16) % (2**63 - 1)

    @staticmethod
    def _build_filter(
        metadata_filter: Optional[dict[str, Any]],
        user_role: Optional[str],
    ) -> Optional[qm.Filter]:
        must: list[qm.FieldCondition] = []

        if user_role and user_role != "admin":
            must.append(
                qm.FieldCondition(
                    key="metadata.access_scope",
                    match=qm.MatchAny(any=[user_role, "all"]),
                )
            )

        if metadata_filter:
            for k, v in metadata_filter.items():
                if v is None:
                    continue
                key = f"metadata.{k}"
                if isinstance(v, list):
                    must.append(qm.FieldCondition(key=key, match=qm.MatchAny(any=[str(x) for x in v])))
                else:
                    must.append(qm.FieldCondition(key=key, match=qm.MatchValue(value=v)))

        if not must:
            return None
        return qm.Filter(must=must)


_qdrant_retrieval_service_instance: Optional[QdrantRetrievalService] = None


def get_qdrant_retrieval_service() -> QdrantRetrievalService:
    global _qdrant_retrieval_service_instance
    if _qdrant_retrieval_service_instance is None:
        _qdrant_retrieval_service_instance = QdrantRetrievalService()
    return _qdrant_retrieval_service_instance

