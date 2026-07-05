from __future__ import annotations
import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel

from app.core.auth import JWTPayload
from app.core.dependencies import require_admin
from app.modules.corpus.repositories.corpus_node_repository import CorpusNodeRepository
from app.modules.corpus.services.corpus_index_service import get_corpus_index_service
from app.modules.corpus.services.corpus_traversal_service import get_corpus_traversal_service
from app.modules.corpus.data.seed import seed_corpus


class TopicCreateRequest(BaseModel):
    slug: str
    title: str
    summary: str = ""
    parent_key: Optional[str] = None  # "topic:<slug>" của cha, None = topic gốc


class TraverseRequest(BaseModel):
    question: str


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


def _node_out(n) -> dict:
    return {
        "node_key": n.node_key,
        "title": n.title,
        "summary": n.summary,
        "parent_keys": n.parent_keys,
        "child_keys": n.child_keys,
        "doc_count": n.doc_count,
        "faq_count": n.faq_count,
    }


@router.get("/stats", summary="Corpus tree statistics")
async def corpus_stats(_admin: JWTPayload = Depends(require_admin)):
    """Tổng số topic, số topic gốc, tổng liên kết file/faq."""
    from app.modules.corpus.models.corpus_node import CorpusNodeDocument
    nodes = await CorpusNodeDocument.find_all().to_list()
    top_level = [n for n in nodes if not n.parent_keys]
    return {
        "total_topics": len(nodes),
        "top_level_topics": len(top_level),
        "total_file_links": sum(len(n.file_ids) for n in nodes),
        "total_faq_links": sum(len(n.faq_ids) for n in nodes),
    }


@router.get("/tree", summary="Full topic tree")
async def corpus_tree(_admin: JWTPayload = Depends(require_admin)):
    """Trả cây topic lồng nhau (đệ quy từ topic gốc) để nhìn cấu trúc cha-con."""
    repo = _get_repo()
    nodes = await repo.get_all()
    node_map = {n.node_key: n for n in nodes}

    def build(key: str, seen: frozenset) -> dict:
        n = node_map.get(key)
        if not n or key in seen:
            return {"node_key": key}
        return {
            "node_key": n.node_key,
            "title": n.title,
            "doc_count": n.doc_count,
            "faq_count": n.faq_count,
            "children": [build(ck, seen | {key}) for ck in n.child_keys],
        }

    roots = [n for n in nodes if not n.parent_keys]
    return {"tree": [build(n.node_key, frozenset()) for n in sorted(roots, key=lambda x: x.node_key)]}


@router.post("/traverse", summary="Test corpus traversal for a question")
async def debug_traverse(
    body: TraverseRequest,
    _admin: JWTPayload = Depends(require_admin),
):
    """
    Chạy traversal thật (LLM drill-down cây topic) cho một câu hỏi.
    Trả về danh sách file/faq ids gộp từ các topic được chọn.
    """
    traversal_svc = get_corpus_traversal_service()
    result = await traversal_svc.traverse(body.question)
    return {
        "question": body.question,
        "file_candidates": [c.leaf_id for c in result.file_candidates],
        "supporting_faqs": [c.leaf_id for c in result.supporting_faqs],
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
    query analysis -> corpus traversal -> metadata/lecturer_only filtering
    -> FAQ fast-path check. Lets you verify role-based filtering and FAQ fast-path
    behavior by simulating different roles, without needing a real user JWT.
    """
    from app.modules.chat.dtos import UserContext
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
            "note": "Gate = NO. Would answer directly without touching the corpus tree.",
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
                {"file_id": c["file_id"], "file_name": c["file_name"]}
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


@router.get("/nodes", summary="List topic nodes")
async def list_corpus_nodes(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    _admin: JWTPayload = Depends(require_admin),
):
    """List topic nodes (flat, phân trang)."""
    from app.modules.corpus.models.corpus_node import CorpusNodeDocument
    nodes = await CorpusNodeDocument.find_all().skip(skip).limit(limit).to_list()
    total = await CorpusNodeDocument.count()
    return {
        "total": total,
        "skip": skip,
        "limit": limit,
        "items": [_node_out(n) for n in nodes],
    }


@router.get("/nodes/{node_key:path}", summary="Get a single topic node")
async def get_corpus_node(
    node_key: str,
    _admin: JWTPayload = Depends(require_admin),
):
    """Get full details of a topic node by its node_key."""
    repo = _get_repo()
    node = await repo.get_by_key(node_key)
    if not node:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Node '{node_key}' not found")
    out = _node_out(node)
    out["keywords"] = node.keywords
    out["file_ids"] = node.file_ids
    out["faq_ids"] = node.faq_ids
    return out


@router.post("/backfill", summary="Trigger corpus backfill (background)")
async def trigger_backfill(_admin: JWTPayload = Depends(require_admin)):
    """
    Fire-and-forget: seed topic tree and re-index all READY files + active FAQs.
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
                        await index_svc.index_file(
                            str(f.id),
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
                        await index_svc.index_faq(
                            str(faq.id),
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


@router.get("/topics", summary="List all topic nodes")
async def list_topics(_admin: JWTPayload = Depends(require_admin)):
    """List all topic nodes with document and FAQ counts."""
    repo = _get_repo()
    nodes = await repo.get_all()
    return {
        "total": len(nodes),
        "items": [_node_out(n) for n in sorted(nodes, key=lambda n: n.node_key)],
    }


@router.post("/topics", summary="Manually create a topic node", status_code=201)
async def create_topic(
    body: TopicCreateRequest,
    _admin: JWTPayload = Depends(require_admin),
):
    """Create a new topic node. slug → node_key 'topic:<slug>'. parent_key = cha trong cây (optional)."""
    from app.modules.corpus.node_keys import slugify_topic

    clean_slug = slugify_topic(body.slug)
    if not clean_slug:
        raise HTTPException(status_code=400, detail="slug invalid after slugification")

    node_key = f"topic:{clean_slug}"
    repo = _get_repo()
    existing = await repo.get_by_key(node_key)
    if existing:
        raise HTTPException(status_code=409, detail=f"Topic '{node_key}' already exists")

    if body.parent_key:
        parent = await repo.get_by_key(body.parent_key)
        if not parent:
            raise HTTPException(status_code=404, detail=f"Parent '{body.parent_key}' not found")

    node = await repo.upsert_node(
        node_key,
        title=body.title,
        summary=body.summary,
        parent_key=body.parent_key,
    )
    logger.info(f"[Corpus] admin created topic: {node_key} (parent={body.parent_key})")
    return {"node_key": node.node_key, "title": node.title, "parent_keys": node.parent_keys}


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
    Chuyển toàn bộ file/faq và topic con từ source sang target, sau đó XÓA source.
    Both node_keys must be 'topic:...' nodes.
    """
    if not node_key.startswith("topic:") or not target_key.startswith("topic:"):
        raise HTTPException(status_code=400, detail="Both keys must be topic: nodes")
    if node_key == target_key:
        raise HTTPException(status_code=400, detail="Source and target must differ")

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
        files_moved += 1

    faqs_moved = 0
    for faq_id in list(source.faq_ids):
        await repo.remove_leaf_link(node_key, "faq", faq_id)
        await repo.add_leaf_link(target_key, "faq", faq_id)
        faqs_moved += 1

    # Topic con của source chuyển sang làm con của target
    children_moved = 0
    for child_key in list(source.child_keys):
        child = await repo.get_by_key(child_key)
        if child:
            child.parent_keys = [target_key if k == node_key else k for k in child.parent_keys]
            await child.save()
            target_doc = await repo.get_by_key(target_key)
            if target_doc and child_key not in target_doc.child_keys:
                target_doc.child_keys.append(child_key)
                await target_doc.save()
            children_moved += 1
    source.child_keys = []
    await source.save()

    await repo.delete_by_key(node_key)

    logger.info(
        f"[Corpus] merge_topics: {node_key} → {target_key} "
        f"({files_moved} files, {faqs_moved} faqs, {children_moved} children moved; source deleted)"
    )
    return {
        "merged_from": node_key,
        "merged_into": target_key,
        "files_moved": files_moved,
        "faqs_moved": faqs_moved,
        "children_moved": children_moved,
        "source_deleted": True,
    }


@router.delete("/nodes/{node_key:path}", summary="Delete a topic node")
async def delete_corpus_node(
    node_key: str,
    _admin: JWTPayload = Depends(require_admin),
):
    """Xóa một topic node (gỡ liên kết cha-con hai chiều trước khi xóa)."""
    repo = _get_repo()
    deleted = await repo.delete_by_key(node_key)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Node '{node_key}' not found")
    logger.info(f"[Corpus] node deleted: {node_key}")
    return {"node_key": node_key, "deleted": True}
