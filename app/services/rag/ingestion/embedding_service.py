"""
Embedding service for chunks.
Sprint 1 uses Google text embedding endpoint via google-genai SDK.
"""

from __future__ import annotations

import asyncio
from typing import Sequence

from app.services.rag.gemini_client import gemini_client


class EmbeddingService:
    """Generate dense vectors for chunk texts."""

    async def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for txt in texts:
            resp = await asyncio.to_thread(
                gemini_client.client.models.embed_content,
                model="text-embedding-004",
                contents=txt,
            )
            emb = getattr(resp, "embeddings", None) or []
            if emb and getattr(emb[0], "values", None):
                vectors.append(list(emb[0].values))
            else:
                vectors.append([])
        return vectors


embedding_service = EmbeddingService()

