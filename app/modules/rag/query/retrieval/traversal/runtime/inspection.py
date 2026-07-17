"""Authorized topic sample hydration for traversal sessions."""

from __future__ import annotations

import asyncio

from app.core.config import settings
from app.modules.corpus.models.corpus_node import CorpusNodeDocument
from app.modules.rag.query.retrieval.hydration.faq_hydrator import get_faq_entities
from app.modules.rag.query.retrieval.hydration.file_hydrator import get_file_entities
from app.modules.rag.query.retrieval.traversal.contracts import TraversalSession
from app.modules.rag.query.retrieval.traversal.runtime.selection import candidate_ids


async def inspect_samples(
    session: TraversalSession,
    node: CorpusNodeDocument,
    scope: str,
) -> dict[str, list[dict[str, str]]]:
    """Hydrate a small authorized sample for the agent to inspect a topic."""
    limit = settings.CORPUS_TRAVERSAL_TOPIC_SAMPLE_LIMIT
    file_ids, faq_ids = candidate_ids(node, scope, session)
    file_ids, faq_ids = file_ids[:limit], faq_ids[:limit]
    file_by_id, faq_by_id = await asyncio.gather(
        get_file_entities(file_ids),
        get_faq_entities(faq_ids),
    )
    return {
        "sampleFiles": [
            {
                "fileId": file_id,
                "name": file_by_id[file_id].file_name,
                "description": file_by_id[file_id].doc_description,
            }
            for file_id in file_ids
            if file_id in file_by_id
        ],
        "sampleFaqs": [
            {"faqId": faq_id, "question": faq_by_id[faq_id].question or ""}
            for faq_id in faq_ids
            if faq_id in faq_by_id
        ],
    }
