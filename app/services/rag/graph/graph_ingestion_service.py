"""
Graph ingestion service: upsert Document/Chunk nodes into Neo4j.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from app.core.config import settings
from app.services.rag.graph.neo4j_client import neo4j_client
from app.services.rag.ingestion.chunking_service import ChunkItem


class GraphIngestionService:
    """Persist parsed chunks with metadata into Neo4j."""

    def upsert_document_and_chunks(
        self,
        *,
        doc_id: str,
        store_id: str,
        title: str,
        chunks: list[ChunkItem],
        embeddings: list[list[float]],
        custom_metadata: Optional[dict] = None,
    ) -> int:
        custom_metadata = custom_metadata or {}
        now = datetime.now(timezone.utc).isoformat()

        doc_params = {
            "doc_id": doc_id,
            "store_id": store_id,
            "title": title,
            "academic_year": self._first_val(custom_metadata, "academic_year"),
            "cohort": self._first_val(custom_metadata, "cohort"),
            "semester": self._first_val(custom_metadata, "semester"),
            "updated_at": now,
        }

        with neo4j_client.driver.session(database=settings.NEO4J_DATABASE) as session:
            session.run(
                """
                MERGE (d:Document {doc_id: $doc_id})
                SET d.store_id = $store_id,
                    d.title = $title,
                    d.academic_year = $academic_year,
                    d.cohort = $cohort,
                    d.semester = $semester,
                    d.updated_at = $updated_at
                """,
                **doc_params,
            )

            for idx, chunk in enumerate(chunks):
                vector = embeddings[idx] if idx < len(embeddings) else []
                session.run(
                    """
                    MERGE (c:Chunk {chunk_id: $chunk_id})
                    SET c.text = $text,
                        c.section_path = $section_path,
                        c.embedding = $embedding,
                        c.updated_at = $updated_at
                    WITH c
                    MATCH (d:Document {doc_id: $doc_id})
                    MERGE (d)-[:HAS_CHUNK]->(c)
                    """,
                    chunk_id=chunk.chunk_id,
                    text=chunk.text,
                    section_path=chunk.section_path,
                    embedding=vector,
                    updated_at=now,
                    doc_id=doc_id,
                )

        return len(chunks)

    @staticmethod
    def _first_val(meta: dict, key: str) -> Optional[str]:
        v = meta.get(key)
        if isinstance(v, list) and v:
            return str(v[0])
        if isinstance(v, str):
            return v
        return None


graph_ingestion_service = GraphIngestionService()

