from __future__ import annotations
import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status, Query

from app.core.auth import JWTPayload
from app.core.dependencies import require_admin
from app.modules.chat.dtos import UserContext
from app.modules.rag.query.analyzer import get_chat_query_analyzer
from app.modules.corpus.models.corpus_node import CorpusNodeDocument
from app.modules.corpus.repositories.corpus_node_repository import CorpusNodeRepository
from app.modules.corpus.repositories.corpus_node_repository import would_create_cycle
from app.modules.corpus.services.corpus_service import get_corpus_service
from app.modules.corpus.utils.node_keys import slugify_topic
from app.modules.faq.models.faq import FaqDocument
from app.modules.files.models.file import FileDocument, FileStatus
from app.modules.files.toc_tree.models.toc_tree import FileTocTree
from app.modules.rag.ingestion.corpus_linker import get_corpus_linker
from app.modules.rag.query.retrieval import get_retrieval_service
from app.modules.rag.query.retrieval.traversal import run_corpus_traversal_pipeline
from scripts.seed_corpus import seed_corpus
from app.modules.corpus.dtos import TopicCreateRequest, TraverseRequest, ChatPreviewRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/debug/corpus", tags=["Debug Corpus"])

_repo: Optional[CorpusNodeRepository] = None
_backfill_running = False


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
        "parent_key": n.parent_key,
        "child_keys": n.child_keys,
        "file_count": n.file_count,
        "faq_count": n.faq_count,
    }


@router.get("/stats", summary="Corpus tree statistics")
async def corpus_stats(_admin: JWTPayload = Depends(require_admin)):
    """Tổng số topic, số topic gốc, tổng liên kết file/faq."""
    nodes = await CorpusNodeDocument.find_all().to_list()
    top_level = [n for n in nodes if n.parent_key is None]
    return {
        "total_topics": len(nodes),
        "top_level_topics": len(top_level),
        "total_direct_file_links": sum(len(n.direct_file_ids) for n in nodes),
        "total_direct_faq_links": sum(len(n.direct_faq_ids) for n in nodes),
    }


@router.get("/tree", summary="Full topic tree")
async def corpus_tree(
    include_leaf_ids: bool = Query(False, description="Kèm direct/subtree leaf ids của từng node"),
    _admin: JWTPayload = Depends(require_admin),
):
    """
    Trả cây topic lồng nhau (đệ quy từ topic gốc) để nhìn cấu trúc cha-con,
    kèm has_content (subtree có file/FAQ nào không — khớp đúng prefilter mà
    traversal dùng để loại nhánh rỗng trước khi đưa cho LLM).
    """
    repo = _get_repo()
    nodes = await repo.get_all()
    node_map = {n.node_key: n for n in nodes}

    def has_content(key: str, seen: set) -> bool:
        n = node_map.get(key)
        if not n:
            return False
        if n.subtree_file_ids or n.subtree_faq_ids:
            return True
        for ck in n.child_keys:
            if ck not in seen:
                seen.add(ck)
                if has_content(ck, seen):
                    return True
        return False

    def build(key: str, seen: frozenset) -> dict:
        n = node_map.get(key)
        if not n or key in seen:
            return {"node_key": key, "error": "missing or cyclic reference"}
        out = {
            "node_key": n.node_key,
            "title": n.title,
            "summary": n.summary,
            "file_count": n.file_count,
            "faq_count": n.faq_count,
            "has_content": has_content(key, {key}),
            "children": [build(ck, seen | {key}) for ck in sorted(n.child_keys)],
        }
        if include_leaf_ids:
            out["direct_file_ids"] = n.direct_file_ids
            out["direct_faq_ids"] = n.direct_faq_ids
            out["subtree_file_ids"] = n.subtree_file_ids
            out["subtree_faq_ids"] = n.subtree_faq_ids
        return out

    roots = [n for n in nodes if n.parent_key is None]
    tree = [build(n.node_key, frozenset()) for n in sorted(roots, key=lambda x: x.node_key)]
    return {
        "total_nodes": len(nodes),
        "total_roots": len(roots),
        "tree": tree,
    }


@router.post("/traverse", summary="Test corpus traversal for a question")
async def debug_traverse(
    body: TraverseRequest,
    _admin: JWTPayload = Depends(require_admin),
):
    """
    Chạy traversal bằng Agent thật (pre-filter 3 key + LLM function calling agent) cho một câu hỏi.
    Trả về danh sách file/faq ids gộp từ các topic được chọn + trace pre-filter.
    """
    metadata_filter: dict = {}
    if body.enrollment_year:
        metadata_filter["enrollment_year"] = {
            "from_year": body.enrollment_year, "to_year": body.enrollment_year,
        }
    if body.academic_year:
        metadata_filter["academic_year"] = {
            "from_year": body.academic_year, "to_year": body.academic_year,
        }

    result = await run_corpus_traversal_pipeline(
        body.question,
        metadata_filter=metadata_filter or None,
        user_role=body.role,
    )

    return {
        "question": body.question,
        "role": body.role,
        "metadata_filter": metadata_filter,
        "prefilter": result.prefilter,
        "file_candidates": [c.leaf_id for c in result.file_candidates],
        "supporting_faqs": [c.leaf_id for c in result.supporting_faqs],
        "total_files": len(result.file_candidates),
        "total_faqs": len(result.supporting_faqs),
    }


@router.post("/chat-preview", summary="Dry-run the chat retrieval pipeline (Stage 1-2) without a real JWT")
async def debug_chat_preview(
    body: ChatPreviewRequest,
    _admin: JWTPayload = Depends(require_admin),
):
    """
    Dry-run quy trình RAG chat qua Stage 1 & 2 để xem kết quả filter và traversal.
    """
    user_context = UserContext(
        user_id="debug-preview",
        name="Debug Preview",
        enrollment_year=body.enrollment_year,
        role=body.role,
    )

    analyzer = get_chat_query_analyzer()
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

    retrieval_context = await get_retrieval_service().retrieve_context(
        question=effective_question,
        metadata_filter=metadata_filter,
        user_role=user_context.role,
    )
    candidate_files = retrieval_context.candidate_files
    faq_docs = retrieval_context.faq_docs

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
        "stage4_would_run": bool(candidate_files),
    }


@router.get("/nodes", summary="List topic nodes")
async def list_corpus_nodes(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    _admin: JWTPayload = Depends(require_admin),
):
    """List topic nodes (flat, phân trang)."""
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
    out["direct_file_ids"] = node.direct_file_ids
    out["direct_faq_ids"] = node.direct_faq_ids
    out["subtree_file_ids"] = node.subtree_file_ids
    out["subtree_faq_ids"] = node.subtree_faq_ids
    return out


@router.post("/backfill", summary="Trigger corpus backfill (background)")
async def trigger_backfill(_admin: JWTPayload = Depends(require_admin)):
    """
    Seed topic tree and re-index all READY files + active FAQs.
    """
    global _backfill_running
    if _backfill_running:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A backfill task is already running."
        )

    _backfill_running = True

    async def _run():
        global _backfill_running
        try:
            repo = _get_repo()
            seeded = await seed_corpus(repo)
            logger.info(f"[Corpus][Backfill] seed: {seeded} nodes created")
            await repo.reset_all_links()
            logger.info("[Corpus][Backfill] cleared direct/subtree corpus links")

            corpus_linker = get_corpus_linker()
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
                        toc_tree = await FileTocTree.find_one(FileTocTree.file_id == str(f.id))
                        await corpus_linker.index_file(
                            str(f.id),
                            display_name=f.display_name or "",
                            doc_description=(toc_tree.doc_description if toc_tree else "") or "",
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
                        await corpus_linker.index_faq(
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
        finally:
            _backfill_running = False

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
    """Create a new topic node."""
    clean_slug = slugify_topic(body.slug)
    if not clean_slug:
        raise HTTPException(status_code=400, detail="slug invalid after slugification")

    node_key = clean_slug
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
    get_corpus_service().clear_cache()
    logger.info(f"[Corpus] admin created topic: {node_key} (parent={body.parent_key})")
    return {"node_key": node.node_key, "title": node.title, "parent_key": node.parent_key}


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
    """
    if node_key == target_key:
        raise HTTPException(status_code=400, detail="Source and target must differ")

    repo = _get_repo()
    source = await repo.get_by_key(node_key)
    target = await repo.get_by_key(target_key)

    if not source:
        raise HTTPException(status_code=404, detail=f"Source '{node_key}' not found")
    if not target:
        raise HTTPException(status_code=404, detail=f"Target '{target_key}' not found")

    # Prevent cycle: target must not be a descendant of source
    if await would_create_cycle(repo, node_key, target_key):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot merge topic '{node_key}' into '{target_key}' because target is a descendant of source."
        )

    files_moved = 0
    for file_id in list(source.direct_file_ids):
        await repo.remove_leaf_link(node_key, "file", file_id)
        await repo.add_leaf_link(target_key, "file", file_id)
        files_moved += 1

    faqs_moved = 0
    for faq_id in list(source.direct_faq_ids):
        await repo.remove_leaf_link(node_key, "faq", faq_id)
        await repo.add_leaf_link(target_key, "faq", faq_id)
        faqs_moved += 1

    # Topic con của source chuyển sang làm con của target
    children_moved = 0
    for child_key in list(source.child_keys):
        child = await repo.get_by_key(child_key)
        if child:
            child.parent_key = target_key
            await child.save()
            target_doc = await repo.get_by_key(target_key)
            if target_doc and child_key not in target_doc.child_keys:
                target_doc.child_keys.append(child_key)
                await target_doc.save()
            children_moved += 1
    source.child_keys = []
    await source.save()
    await repo.rebuild_node_and_ancestors(target_key)
    if source.parent_key:
        await repo.rebuild_node_and_ancestors(source.parent_key)

    await repo.delete_by_key(node_key)

    get_corpus_service().clear_cache()
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
    get_corpus_service().clear_cache()
    logger.info(f"[Corpus] node deleted: {node_key}")
    return {"node_key": node_key, "deleted": True}
