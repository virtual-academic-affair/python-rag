"""
Graphiti retrieval service (Phase 1 skeleton).

Phase 3 will implement hybrid retrieval + metadata filtering using Graphiti query APIs.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


class GraphitiRetrievalService:
    """Facade for Graphiti retrieval."""

    async def retrieve_chunks(
        self,
        query: str,
        store_id: str,
        metadata_filter: Optional[Dict[str, Any]] = None,
        top_k: int = 8,
    ) -> List[Dict[str, Any]]:
        """Retrieve candidate chunks for generation context."""
        raise NotImplementedError("Phase 3: implement Graphiti retrieval")


graphiti_retrieval_service = GraphitiRetrievalService()

