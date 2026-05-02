"""
Shared Embedding Service using Gemini.
Provides a unified way to embed text across the application.
"""
from typing import List, Optional
import logging

from google import genai
from google.genai import types

from app.core.config import settings

logger = logging.getLogger(__name__)

_embedding_service_instance: Optional['EmbeddingService'] = None


class EmbeddingService:
    def __init__(self):
        self._genai_client = genai.Client(api_key=settings.GOOGLE_API_KEY)
        self._embed_model_name = settings.GEMINI_EMBEDDING_MODEL

    async def embed(self, text: str) -> List[float]:
        """Generate embedding vector for a given text using Gemini."""
        response = await self._genai_client.aio.models.embed_content(
            model=self._embed_model_name,
            contents=text,
            config=types.EmbedContentConfig(output_dimensionality=settings.QDRANT_VECTOR_SIZE)
        )
        return response.embeddings[0].values


def get_embedding_service() -> EmbeddingService:
    """Get the singleton instance of EmbeddingService."""
    global _embedding_service_instance
    if _embedding_service_instance is None:
        _embedding_service_instance = EmbeddingService()
    return _embedding_service_instance
