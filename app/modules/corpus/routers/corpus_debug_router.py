from __future__ import annotations
import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel

from app.core.auth import JWTPayload
from app.core.dependencies import require_admin
from app.modules.corpus.models.corpus_node import NodeType, NodeStatus
from app.modules.corpus.repositories.corpus_node_repository import CorpusNodeRepository
from app.modules.corpus.services.corpus_index_service import get_corpus_index_service
from app.modules.corpus.services.corpus_traversal_service import get_corpus_traversal_service
from app.modules.corpus.data.seed import seed_corpus


class TopicCreateRequest(BaseModel):
    slug: str
    title: str
    summary: str = ""
    parent_key: Optional[str] = None  # "topic:<slug>" cha; None → top-level dưới axis:topics


class TraverseRequest(BaseModel):
    question: str
    metadata_filter: dict = {}


class ChatPreviewRequest(BaseModel):
    question: str
    role: str = "student"  # student | lecture | admin — test lecturer_only filtering
    enrollment_year: Optional[int] = None

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


@router.post("/traverse", summary="Test corpus traversal for a question")
async def debug_traverse(
    body: TraverseRequest,
    _admin: JWTPayload = Depends(require_admin),
):
    """
    Run full Phase B traversal (BƯỚC 1 prefilter + BƯỚC 2 LLM topic selection +
    resolve_candidates) for a given question and metadata_filter.
    Returns which topics were selected, which files/FAQs resolved, and their scores.
    Useful for verifying the graph is wired correctly without going through chat.
    """
    traversal_svc = get_corpus_traversal_service()
    result = await traversal_svc.traverse(body.question, body.metadata_filter)
    return {
        "question": body.question,
        "metadata_filter": body.metadata_filter,
        "file_candidates": [
            {"leaf_id": c.leaf_id, "score": c.score} for c in result.file_candidates
        ],
        "supporting_faqs": [
            {"leaf_id": c.leaf_id, "score": c.score} for c in result.supporting_faqs
        ],
        "total_files": len(result.file_candidates),
        "total_faqs": len(result.supporting_faqs),
    }


@router.post("/chat-preview", summary="Dry-run the full chat pipeline (Stage 1-3) without a real JWT")
async def debug_chat_preview(
    body: ChatPreviewRequest,
    _admin: JWTPayload = Depends(require_admin),
):
    """
    Runs the real chat pipeline up to (but not including) Stage 4's agent loop:
    query analysis -> metadata_filter -> corpus traversal -> lecturer_only filtering
    -> FAQ fast-path check. Lets you verify role-based filtering and FAQ fast-path
    behavior by simulating different roles, without needing a real user JWT or
    incurring the cost of the full document-reading agent loop.
    """
    from app.modules.chat.dtos import UserContext, ChatHistoryItem
    from app.modules.chat.services.chat_service import get_chat_service
    from app.modules.chat.services.query_analyzer_service import get_query_analyzer

    user_context = UserContext(
        user_id="debug-preview",
        name="Debug Preview",
        enrollment_year=body.enrollment_year,
        role=body.role,
    )

    analyzer = get_query_analyzer()
    analysis = await analyzer.analyze_query(body.question, [])
    effective_question = analysis["effective_question"]
    needs_rag = analysis["needs_rag"]
    metadata_filter = analysis.get("metadata_filter") or {}
    if not metadata_filter.get("enrollment_year") and body.enrollment_year:
        metadata_filter["enrollment_year"] = {
            "from_year": body.enrollment_year,
            "to_year": body.enrollment_year,
        }

    if not needs_rag:
        return {
            "stage1_query_analysis": {
                "effective_question": effective_question,
                "needs_rag": False,
                "metadata_filter": metadata_filter,
            },
            "note": "Gate = NO. Would answer directly without touching the corpus graph.",
        }

    chat_svc = get_chat_service()
    state = await chat_svc._prepare_chat_state(
        effective_question, user_context, [], metadata_filter
    )
    candidate_files = state["candidate_files"]
    faq_docs = state.get("faq_docs") or []

    faq_answer = await chat_svc._try_faq_fast_path(effective_question, faq_docs)

    return {
        "stage1_query_analysis": {
            "effective_question": effective_question,
            "needs_rag": needs_rag,
            "metadata_filter": metadata_filter,
        },
        "stage2_traversal_and_filtering": {
            "role_used_for_filtering": body.role,
            "candidate_files": [
                {"file_id": c["file_id"], "file_name": c["file_name"], "doc_score": c["doc_score"]}
                for c in candidate_files
            ],
            "supporting_faqs": [
                {"question": f.question, "is_active": f.is_active} for f in faq_docs
            ],
        },
        "stage3_faq_fast_path": {
            "triggered": faq_answer is not None,
            "answer": faq_answer,
        },
        "stage4_would_run": faq_answer is None and bool(candidate_files),
    }


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
                        meta_dict = f.custom_metadata.model_dump(mode="json") if f.custom_metadata else {}
                        await index_svc.index_file(
                            str(f.id),
                            meta_dict,
                            display_name=f.display_name or "",
                            toc_headings=f.table_of_contents or [],
                        )
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
                        await index_svc.index_faq(
                            str(faq.id),
                            meta,
                            question=faq.question or "",
                            answer_markdown=faq.answer_markdown or "",
                        )
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


@router.get("/topics", summary="List all active topic nodes")
async def list_topics(_admin: JWTPayload = Depends(require_admin)):
    """List all active topic nodes with document and FAQ counts."""
    from app.modules.corpus.models.corpus_node import CorpusNodeDocument
    nodes = await CorpusNodeDocument.find(
        {"node_type": NodeType.TOPIC.value, "status": NodeStatus.ACTIVE.value}
    ).to_list()
    return {
        "total": len(nodes),
        "items": [
            {
                "node_key": n.node_key,
                "title": n.title,
                "summary": n.summary,
                "doc_count": n.doc_count,
                "faq_count": n.faq_count,
                "status": n.status,
            }
            for n in sorted(nodes, key=lambda n: n.node_key)
        ],
    }


@router.post("/topics", summary="Manually create a topic node", status_code=201)
async def create_topic(
    body: TopicCreateRequest,
    _admin: JWTPayload = Depends(require_admin),
):
    """Create a new topic node manually. slug → node_key 'topic:<slug>'."""
    from app.modules.corpus.node_keys import slugify_topic

    clean_slug = slugify_topic(body.slug)
    if not clean_slug:
        raise HTTPException(status_code=400, detail="slug invalid after slugification")

    node_key = f"topic:{clean_slug}"
    repo = _get_repo()
    existing = await repo.get_by_key(node_key)
    if existing:
        raise HTTPException(status_code=409, detail=f"Topic '{node_key}' already exists")

    parent_key = "axis:topics"
    if body.parent_key:
        if not body.parent_key.startswith("topic:"):
            raise HTTPException(status_code=400, detail="parent_key must be a 'topic:...' node")
        parent = await repo.get_by_key(body.parent_key)
        if not parent:
            raise HTTPException(status_code=404, detail=f"Parent '{body.parent_key}' not found")
        parent_key = body.parent_key

    node = await repo.upsert_node(
        node_key,
        node_type=NodeType.TOPIC,
        title=body.title,
        summary=body.summary,
        axis_parent_key=parent_key,
    )
    logger.info(f"[Corpus] admin created topic: {node_key} (parent={parent_key})")
    return {"node_key": node.node_key, "title": node.title, "parent_key": parent_key, "status": node.status}


@router.post(
    "/topics/{node_key:path}/merge-into/{target_key:path}",
    summary="Merge source topic into target topic",
)
async def merge_topics(
    node_key: str,
    target_key: str,
    _admin: JWTPayload = Depends(require_admin),
):
    """
    Re-link all files and FAQs from source topic to target topic, then archive source.
    Both node_keys must be 'topic:...' nodes.
    """
    if not node_key.startswith("topic:") or not target_key.startswith("topic:"):
        raise HTTPException(status_code=400, detail="Both keys must be topic: nodes")

    repo = _get_repo()
    source = await repo.get_by_key(node_key)
    target = await repo.get_by_key(target_key)

    if not source:
        raise HTTPException(status_code=404, detail=f"Source '{node_key}' not found")
    if not target:
        raise HTTPException(status_code=404, detail=f"Target '{target_key}' not found")

    files_moved = 0
    for file_id in list(source.file_ids):
        await repo.remove_leaf_link(node_key, "file", file_id)
        await repo.add_leaf_link(target_key, "file", file_id)
        leaf = await repo.get_by_key(f"file:{file_id}")
        if leaf and node_key in leaf.parent_keys:
            leaf.parent_keys = list(dict.fromkeys(
                target_key if k == node_key else k for k in leaf.parent_keys
            ))
            await leaf.save()
        files_moved += 1

    faqs_moved = 0
    for faq_id in list(source.faq_ids):
        await repo.remove_leaf_link(node_key, "faq", faq_id)
        await repo.add_leaf_link(target_key, "faq", faq_id)
        leaf = await repo.get_by_key(f"faq:{faq_id}")
        if leaf and node_key in leaf.parent_keys:
            leaf.parent_keys = list(dict.fromkeys(
                target_key if k == node_key else k for k in leaf.parent_keys
            ))
            await leaf.save()
        faqs_moved += 1

    source.status = NodeStatus.ARCHIVED
    await source.save()

    logger.info(
        f"[Corpus] merge_topics: {node_key} → {target_key} "
        f"({files_moved} files, {faqs_moved} faqs moved)"
    )
    return {
        "merged_from": node_key,
        "merged_into": target_key,
        "files_moved": files_moved,
        "faqs_moved": faqs_moved,
        "source_status": "archived",
    }
