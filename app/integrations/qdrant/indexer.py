"""
Qdrant integration for generating embeddings and indexing into Qdrant.
"""

import logging
from typing import Any, List, Optional
import hashlib
import asyncio
from qdrant_client.http import models as qm

from app.core.config import settings

from google import genai
from app.integrations.qdrant.client import get_qdrant_retrieval_service
from google.genai import types
from app.modules.metadata.models.value_objects import FileMetadata

logger = logging.getLogger(__name__)

class QdrantIndexer:
    """Handles embedding chunks and indexing them into Qdrant."""
    
    def __init__(self):
        self._genai_client = genai.Client(api_key=settings.GOOGLE_API_KEY)
        self._embed_model_name = "models/gemini-embedding-001"
        self._qdrant_svc = get_qdrant_retrieval_service()
        self._qdrant_client = self._qdrant_svc.qdrant_client_instance
        
    async def ensure_collection(self) -> None:
        """Create the collection in Qdrant if it does not exist (delegate to service)."""
        await self._qdrant_svc.ensure_collection()

    def _stable_point_id(self, chunk_id: str) -> str:
        """Qdrant accepts UUID or unsigned integer. Using a uuid format derived from chunk_id."""
        h = hashlib.md5(chunk_id.encode("utf-8")).hexdigest()
        return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"

    async def ingest_chunks(self, chunks_data: List[dict]) -> tuple[int, List[str]]:
        """
        Embed and ingest chunks into Qdrant (native async).
        
        Args:
            chunks_data: List of dicts representing chunks (with chunk_id, text, metadata)
        Returns:
            Tuple of (number of points successfully ingested, list of point IDs)
        """
        await self.ensure_collection()
        
        # Batch collect texts to embed — filter out empty-text chunks
        texts = [c.get("text", "") for c in chunks_data]
        if not texts or all(not t.strip() for t in texts):
            return 0, []

        # Gemini API giới hạn tối đa 100 requests/batch — chia nhỏ nếu cần
        EMBED_BATCH_SIZE = 100
        embeddings = []
        for i in range(0, len(texts), EMBED_BATCH_SIZE):
            batch_texts = texts[i:i + EMBED_BATCH_SIZE]
            logger.info(f"[Indexer] Embedding batch {i // EMBED_BATCH_SIZE + 1} ({len(batch_texts)} chunks)...")
            response = await self._genai_client.aio.models.embed_content(
                model=self._embed_model_name,
                contents=batch_texts,
                config=types.EmbedContentConfig(output_dimensionality=settings.QDRANT_VECTOR_SIZE)
            )
            embeddings.extend([e.values for e in response.embeddings])
        
        points = []
        for i, chunk in enumerate(chunks_data):
            meta = chunk.get("metadata")
            try:
                if isinstance(meta, dict):
                    flat_meta = FileMetadata(**meta).to_qdrant_payload()
                elif hasattr(meta, "to_qdrant_payload"):
                    flat_meta = meta.to_qdrant_payload()
                else:
                    flat_meta = {}
            except Exception as meta_err:
                logger.warning(f"[Indexer] Failed to parse chunk metadata, using empty: {meta_err}")
                flat_meta = {}

            payload = {
                "file_id": chunk.get("file_id"),
                "file_name": chunk.get("file_name"),
                "chunk_index": chunk.get("chunk_index"),
                "text": chunk.get("text", ""),
                "section_path": chunk.get("section_path"),
                "metadata": flat_meta,
            }

            point_id = self._stable_point_id(chunk["chunk_id"])
            points.append(qm.PointStruct(
                id=point_id,
                vector=embeddings[i],
                payload=payload
            ))

        await asyncio.to_thread(
            self._qdrant_client.upsert,
            collection_name=settings.QDRANT_COLLECTION_NAME,
            points=points,
            wait=True,
        )
        return len(points), [p.id for p in points]
        
    async def delete_by_file_id(self, file_id: str) -> None:
        """
        Delete all chunks associated with a file_id from Qdrant.
        """
        await self.ensure_collection()
        await asyncio.to_thread(
            self._qdrant_client.delete,
            collection_name=settings.QDRANT_COLLECTION_NAME,
            points_selector=qm.FilterSelector(
                filter=qm.Filter(
                    must=[
                        qm.FieldCondition(
                            key="file_id",
                            match=qm.MatchValue(value=file_id)
                        )
                    ]
                )
            )
        )

    async def delete_by_file_id_exclude_points(self, file_id: str, exclude_point_ids: List[str]) -> None:
        """
        Delete all chunks associated with a file_id from Qdrant, except the ones with the specified point IDs.
        """
        if not exclude_point_ids:
            await self.delete_by_file_id(file_id)
            return

        await self.ensure_collection()
        await asyncio.to_thread(
            self._qdrant_client.delete,
            collection_name=settings.QDRANT_COLLECTION_NAME,
            points_selector=qm.FilterSelector(
                filter=qm.Filter(
                    must=[
                        qm.FieldCondition(
                            key="file_id",
                            match=qm.MatchValue(value=file_id)
                        )
                    ],
                    must_not=[
                        qm.HasIdCondition(has_id=exclude_point_ids)
                    ]
                )
            )
        )

    async def update_payload_by_file_id(
        self,
        file_id: str,
        new_metadata: Optional[dict] = None,
        file_name: Optional[str] = None
    ) -> None:
        """
        Update the payload (metadata and/or file_name) for all chunks associated with a file_id.
        """
        await self.ensure_collection()
        
        payload_to_update = {}
        if file_name is not None:
            payload_to_update["file_name"] = file_name
            
        if new_metadata is not None:
            try:
                flat_meta = FileMetadata(**new_metadata).to_qdrant_payload()
                payload_to_update["metadata"] = flat_meta
            except Exception as e:
                logger.warning(f"Failed to parse metadata for Qdrant update: {e}. Skipping metadata update.")
                
        if not payload_to_update:
            return

        await asyncio.to_thread(
            self._qdrant_client.set_payload,
            collection_name=settings.QDRANT_COLLECTION_NAME,
            payload=payload_to_update,
            points=qm.FilterSelector(
                filter=qm.Filter(
                    must=[
                        qm.FieldCondition(
                            key="file_id",
                            match=qm.MatchValue(value=file_id)
                        )
                    ]
                )
            ),
            wait=True,
        )

_qdrant_indexer_instance: Optional[QdrantIndexer] = None

def get_qdrant_indexer() -> QdrantIndexer:
    global _qdrant_indexer_instance
    if _qdrant_indexer_instance is None:
        _qdrant_indexer_instance = QdrantIndexer()
    return _qdrant_indexer_instance
