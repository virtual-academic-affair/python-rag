"""Authorized topic sample hydration for traversal sessions."""

from __future__ import annotations

import asyncio

from app.core.config import settings
from app.modules.corpus.models.corpus_node import CorpusNodeDocument
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
    from app.modules.files.services.file_service import get_file_service
    from app.modules.files.toc_tree.repositories.toc_tree_repository import FileTocTreeRepository
    from app.modules.faq.services.faq_service import get_faq_service

    file_svc = get_file_service()
    faq_svc = await get_faq_service()
    files, faqs = await asyncio.gather(
        file_svc.get_files_by_ids(file_ids),
        faq_svc.get_faqs_by_ids(faq_ids),
    )
    toc_docs = await FileTocTreeRepository().find_by_file_ids(file_ids)
    toc_by_file_id = {toc.file_id: toc for toc in toc_docs}
    file_by_id = {str(file.id): file for file in files}
    faq_by_id = {str(faq.id): faq for faq in faqs}
    return {
        "sampleFiles": [
            {
                "fileId": file_id,
                "name": file_by_id[file_id].display_name or "",
                "description": (toc_by_file_id.get(file_id).doc_description if toc_by_file_id.get(file_id) else "") or "",
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
