from __future__ import annotations
import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status, Query

from app.core.auth import JWTPayload
from app.core.dependencies import require_admin
from app.modules.corpus.models.corpus_node import NodeType, NodeStatus
from app.modules.corpus.repositories.corpus_node_repository import CorpusNodeRepository
from app.modules.corpus.services.corpus_index_service import get_corpus_index_service
from app.modules.corpus.services.corpus_traversal_service import get_corpus_traversal_service
from app.modules.corpus.data.seed import seed_corpus

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/debug/corpus", tags=["Debug Corpus"])

_repo: Optional[CorpusNodeRepository] = None


def _get_repo() -> CorpusNodeRepository:
    global _repo
    if _repo is None:
        _repo = CorpusNodeRepository()
    return _repo


@router.get("/stats", summary="Corpus graph statistics")
async def corpus_stats(_admin: JWTPayload = Depends(require_admin)):
    """Return node counts by type and status."""
    from app.modules.corpus.models.corpus_node import CorpusNodeDocument
    total = await CorpusNodeDocument.count()
    counts = {}
    for nt in NodeType:
        active = await CorpusNodeDocument.find(
            {"node_type": nt.value, "status": NodeStatus.ACTIVE.value}
        ).count()
        archived = await CorpusNodeDocument.find(
            {"node_type": nt.value, "status": NodeStatus.ARCHIVED.value}
        ).count()
        if active + archived > 0:
            counts[nt.value] = {"active": active, "archived": archived}
    return {"total": total, "by_type": counts}


@router.get("/nodes", summary="List corpus nodes")
async def list_corpus_nodes(
    node_type: Optional[NodeType] = Query(None, description="Filter by node_type"),
    node_status: Optional[NodeStatus] = Query(None, alias="status", description="Filter by status"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    _admin: JWTPayload = Depends(require_admin),
):
    """List corpus nodes with optional filters."""
    from app.modules.corpus.models.corpus_node import CorpusNodeDocument
    query_filter = {}
    if node_type:
        query_filter["node_type"] = node_type.value
    if node_status:
        query_filter["status"] = node_status.value

    nodes = await CorpusNodeDocument.find(query_filter).skip(skip).limit(limit).to_list()
    total = await CorpusNodeDocument.find(query_filter).count()
    return {
        "total": total,
        "skip": skip,
        "limit": limit,
        "items": [
            {
                "node_key": n.node_key,
                "node_type": n.node_type,
                "title": n.title,
                "status": n.status,
                "doc_count": n.doc_count,
                "faq_count": n.faq_count,
                "parent_keys": n.parent_keys,
                "child_keys": n.child_keys,
            }
            for n in nodes
        ],
    }


@router.get("/nodes/{node_key:path}", summary="Get a single corpus node")
async def get_corpus_node(
    node_key: str,
    _admin: JWTPayload = Depends(require_admin),
):
    """Get full details of a corpus node by its node_key."""
    repo = _get_repo()
    node = await repo.get_by_key(node_key)
    if not node:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Node '{node_key}' not found")
    return {
        "node_key": node.node_key,
        "node_type": node.node_type,
        "title": node.title,
        "summary": node.summary,
        "keywords": node.keywords,
        "metadata_filter": node.metadata_filter,
        "file_ids": node.file_ids,
        "faq_ids": node.faq_ids,
        "child_keys": node.child_keys,
        "parent_keys": node.parent_keys,
        "doc_count": node.doc_count,
        "faq_count": node.faq_count,
        "status": node.status,
    }


@router.post("/backfill", summary="Trigger corpus backfill (background)")
async def trigger_backfill(_admin: JWTPayload = Depends(require_admin)):
    """
    Fire-and-forget: seed root/axes and re-index all READY files + active FAQs.
    Returns immediately; progress in server logs.
    """
    async def _run():
        try:
            from app.modules.files.models.file import FileDocument, FileStatus
            from app.modules.faq.models.faq import FaqDocument
            repo = _get_repo()
            seeded = await seed_corpus(repo)
            logger.info(f"[Corpus][Backfill] seed: {seeded} nodes created")

            index_svc = get_corpus_index_service()
            files_ok = files_err = faqs_ok = faqs_err = 0
            BATCH = 100

            skip = 0
            while True:
                batch = await FileDocument.find(
                    FileDocument.status == FileStatus.READY
                ).skip(skip).limit(BATCH).to_list()
                if not batch:
                    break
                for f in batch:
                    try:
                        await index_svc.index_file(str(f.id), f.custom_metadata or {})
                        files_ok += 1
                    except Exception as e:
                        logger.error(f"[Corpus][Backfill] index_file {f.id}: {e}")
                        files_err += 1
                skip += BATCH
                if len(batch) < BATCH:
                    break

            skip = 0
            while True:
                batch = await FaqDocument.find(
                    FaqDocument.is_active == True
                ).skip(skip).limit(BATCH).to_list()
                if not batch:
                    break
                for faq in batch:
                    try:
                        meta = faq.metadata_filter.model_dump(mode="json") if faq.metadata_filter else {}
                        await index_svc.index_faq(str(faq.id), meta)
                        faqs_ok += 1
                    except Exception as e:
                        logger.error(f"[Corpus][Backfill] index_faq {faq.id}: {e}")
                        faqs_err += 1
                skip += BATCH
                if len(batch) < BATCH:
                    break

            logger.info(
                f"[Corpus][Backfill] Done. Files {files_ok}/{files_ok+files_err} ok, "
                f"FAQs {faqs_ok}/{faqs_ok+faqs_err} ok."
            )
        except Exception as e:
            logger.error(f"[Corpus][Backfill] Fatal error: {e}", exc_info=True)

    asyncio.create_task(_run())
    return {"status": "backfill_started", "message": "Check server logs for progress"}


@router.patch("/nodes/{node_key:path}/archive", summary="Archive a corpus node")
async def archive_corpus_node(
    node_key: str,
    _admin: JWTPayload = Depends(require_admin),
):
    """Set a corpus node's status to archived."""
    repo = _get_repo()
    node = await repo.get_by_key(node_key)
    if not node:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Node '{node_key}' not found")
    node.status = NodeStatus.ARCHIVED
    await node.save()
    logger.info(f"[Corpus] node archived: {node_key}")
    return {"node_key": node_key, "status": "archived"}
