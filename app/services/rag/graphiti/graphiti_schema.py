"""
Graphiti schema bootstrap (Phase 1).

This module prepares required constraints/indexes for Graphiti-backed retrieval.
In Phase 2+, ingestion/retrieval services will rely on these objects.
"""

from __future__ import annotations

import logging

from app.core.config import settings
from app.services.rag.graphiti.graphiti_client import graphiti_client

logger = logging.getLogger(__name__)


class GraphitiSchemaService:
    """Create baseline constraints and indexes for Graphiti graph storage."""

    @staticmethod
    def initialize_schema() -> None:
        statements = [
            "CREATE CONSTRAINT document_doc_id IF NOT EXISTS FOR (d:Document) REQUIRE d.doc_id IS UNIQUE",
            "CREATE CONSTRAINT chunk_chunk_id IF NOT EXISTS FOR (c:Chunk) REQUIRE c.chunk_id IS UNIQUE",
            "CREATE CONSTRAINT entity_key IF NOT EXISTS FOR (e:Entity) REQUIRE e.entity_key IS UNIQUE",
            "CREATE INDEX document_store_id IF NOT EXISTS FOR (d:Document) ON (d.store_id)",
            "CREATE INDEX document_year IF NOT EXISTS FOR (d:Document) ON (d.academic_year)",
            "CREATE INDEX document_cohort IF NOT EXISTS FOR (d:Document) ON (d.cohort)",
            "CREATE FULLTEXT INDEX chunk_text_ft IF NOT EXISTS FOR (c:Chunk) ON EACH [c.text]",
            (
                "CREATE VECTOR INDEX chunk_embedding_index IF NOT EXISTS "
                "FOR (c:Chunk) ON (c.embedding) "
                f"OPTIONS {{indexConfig: {{`vector.dimensions`: {settings.GRAPHITI_VECTOR_DIMENSIONS}, `vector.similarity_function`: 'cosine'}}}}"
            ),
        ]

        with graphiti_client.driver.session(database=settings.GRAPHITI_DATABASE) as session:
            for stmt in statements:
                session.run(stmt)

        logger.info("Graphiti schema initialized successfully")


graphiti_schema_service = GraphitiSchemaService()

