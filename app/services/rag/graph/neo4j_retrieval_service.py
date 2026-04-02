"""
Neo4j retrieval service for GraphRAG query flow.
Combines vector search + fulltext search and returns unified chunk candidates.
"""

from __future__ import annotations

from typing import Any, Optional

from app.core.config import settings
from app.services.rag.graph.neo4j_client import neo4j_client
from app.services.rag.ingestion.embedding_service import embedding_service


class Neo4jRetrievalService:
    """Retrieve relevant chunks from Neo4j for QA."""

    async def retrieve_chunks(
        self,
        *,
        question: str,
        store_id: str,
        metadata_filter: Optional[dict[str, Any]] = None,
        top_k: int = 8,
    ) -> list[dict[str, Any]]:
        query_vector = (await embedding_service.embed_texts([question]))[0]

        with neo4j_client.driver.session(database=settings.NEO4J_DATABASE) as session:
            vector_hits = self._vector_search(
                session=session,
                vector=query_vector,
                store_id=store_id,
                metadata_filter=metadata_filter or {},
                limit=max(top_k * 2, 12),
            )
            text_hits = self._fulltext_search(
                session=session,
                question=question,
                store_id=store_id,
                metadata_filter=metadata_filter or {},
                limit=max(top_k * 2, 12),
            )

        merged = self._merge_hits(vector_hits, text_hits)
        merged.sort(key=lambda x: x.get("score", 0.0), reverse=True)
        return merged[:top_k]

    def _vector_search(self, *, session, vector: list[float], store_id: str, metadata_filter: dict[str, Any], limit: int) -> list[dict[str, Any]]:
        cypher = """
        CALL db.index.vector.queryNodes('chunk_embedding_index', $limit, $vector)
        YIELD node, score
        MATCH (d:Document)-[:HAS_CHUNK]->(node)
        WHERE d.store_id = $store_id
          AND ($academic_year IS NULL OR d.academic_year = $academic_year)
          AND ($cohort IS NULL OR d.cohort = $cohort)
          AND ($semester IS NULL OR d.semester = $semester)
        RETURN node.chunk_id AS chunk_id,
               node.text AS text,
               node.section_path AS section_path,
               d.doc_id AS doc_id,
               d.title AS title,
               score AS score
        ORDER BY score DESC
        LIMIT $limit
        """
        rows = session.run(
            cypher,
            vector=vector,
            limit=limit,
            store_id=store_id,
            academic_year=self._first_filter_value(metadata_filter, "academic_year"),
            cohort=self._first_filter_value(metadata_filter, "cohort"),
            semester=self._first_filter_value(metadata_filter, "semester"),
        )
        return [dict(r) for r in rows]

    def _fulltext_search(self, *, session, question: str, store_id: str, metadata_filter: dict[str, Any], limit: int) -> list[dict[str, Any]]:
        cypher = """
        CALL db.index.fulltext.queryNodes('chunk_text_ft', $query, {limit: $limit})
        YIELD node, score
        MATCH (d:Document)-[:HAS_CHUNK]->(node)
        WHERE d.store_id = $store_id
          AND ($academic_year IS NULL OR d.academic_year = $academic_year)
          AND ($cohort IS NULL OR d.cohort = $cohort)
          AND ($semester IS NULL OR d.semester = $semester)
        RETURN node.chunk_id AS chunk_id,
               node.text AS text,
               node.section_path AS section_path,
               d.doc_id AS doc_id,
               d.title AS title,
               score AS score
        ORDER BY score DESC
        LIMIT $limit
        """
        rows = session.run(
            cypher,
            query=question,
            limit=limit,
            store_id=store_id,
            academic_year=self._first_filter_value(metadata_filter, "academic_year"),
            cohort=self._first_filter_value(metadata_filter, "cohort"),
            semester=self._first_filter_value(metadata_filter, "semester"),
        )
        return [dict(r) for r in rows]

    @staticmethod
    def _merge_hits(vector_hits: list[dict[str, Any]], text_hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
        merged: dict[str, dict[str, Any]] = {}

        for row in vector_hits:
            cid = row.get("chunk_id")
            if not cid:
                continue
            merged[cid] = {
                **row,
                "score": float(row.get("score") or 0.0) * 0.7,
            }

        for row in text_hits:
            cid = row.get("chunk_id")
            if not cid:
                continue
            if cid not in merged:
                merged[cid] = {
                    **row,
                    "score": float(row.get("score") or 0.0) * 0.3,
                }
            else:
                merged[cid]["score"] = float(merged[cid].get("score") or 0.0) + float(row.get("score") or 0.0) * 0.3

        return list(merged.values())

    @staticmethod
    def _first_filter_value(metadata_filter: dict[str, Any], key: str) -> Optional[str]:
        value = metadata_filter.get(key)
        if isinstance(value, list) and value:
            return str(value[0])
        if isinstance(value, str):
            return value
        return None


neo4j_retrieval_service = Neo4jRetrievalService()

