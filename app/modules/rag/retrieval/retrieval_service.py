"""
Retrieval Service - Vectorless RAG logic.
Uses PageIndex structural context and LLM-based document navigation.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from google.genai import types

from app.core.config import settings
from app.integrations.pageindex.client import get_page_index_client
from app.integrations.llm.gemini import gemini_client
from app.modules.metadata.utils.filter_builder import get_filter_builder
from app.modules.files.models.file import FileStatus
from app.modules.files.toc_tree.models.toc_tree import serialize_toc_structure
from app.modules.files.toc_tree.repositories.toc_tree_repository import FileTocTreeRepository
from app.modules.files.repositories.file_repository import FileRepository
from app.modules.rag.retrieval.navigator import (
    CatalogEntry,
    DocumentNavigator,
    build_candidate_files,
)
from app.utils.retry import async_retry

logger = logging.getLogger(__name__)

class RetrievalService:
    def __init__(self):
        self._filter_builder = get_filter_builder()
        self._page_index = get_page_index_client()
        self._toc_repo = FileTocTreeRepository()
        self._file_repo = FileRepository()

    @property
    def page_index(self):
        """Expose PageIndex client for Agent tools."""
        return self._page_index

    async def retrieve_candidate_files(
        self,
        query: str,
        metadata_filter: Optional[Dict[str, Any]] = None,
        max_files: int = 5,
    ) -> List[Dict[str, Any]]:
        """Fetch relevant files using LLM-based document navigation over the metadata catalog."""
        return await self.retrieve_candidate_files_via_navigator(
            query=query,
            metadata_filter=metadata_filter,
            max_files=max_files,
        )

    async def _gemini_navigate(self, prompt: str) -> str:
        """Adapter: run the navigator prompt through Gemini, return raw JSON text."""
        model = settings.RETRIEVAL_NAVIGATOR_MODEL or settings.GEMINI_MODEL
        resp = await async_retry(
            gemini_client.client.aio.models.generate_content,
            model=model,
            contents=[prompt],
            config=types.GenerateContentConfig(
                temperature=0.0,
                response_mime_type="application/json",
            ),
        )
        return resp.text or "{}"

    async def retrieve_candidate_files_via_navigator(
        self,
        query: str,
        metadata_filter: Optional[Dict[str, Any]] = None,
        max_files: int = 5,
    ) -> List[Dict[str, Any]]:
        """Vectorless candidate finder: metadata folder filter -> LLM catalog navigation.

        Output shape matches retrieve_candidate_files so the agent loop is untouched.
        """
        # 1. Metadata acts as the deterministic "folder" layer (Mongo query, no vectors).
        mongo_filter = await self._filter_builder.build_mongo_filter(
            metadata_filter or {},
            mongo_prefix="custom_metadata",
            skip_validation=True,
        )
        mongo_filter["status"] = FileStatus.READY.value

        files, _ = await self._file_repo.list_files(
            mongo_filter, skip=0, limit=settings.RETRIEVAL_NAVIGATOR_MAX_CATALOG
        )
        if not files:
            logger.info(f"[Navigator] Không có file READY nào khớp folder/metadata cho query '{query[:50]}...'")
            return []

        file_ids = [str(f.id) for f in files]
        toc_docs = await self._toc_repo.find_by_file_ids(file_ids)
        toc_map = {t.file_id: t for t in toc_docs}

        # 2. Build the compact catalog the LLM will reason over.
        entries: List[CatalogEntry] = []
        for f in files:
            fid = str(f.id)
            meta = f.custom_metadata
            toc = toc_map.get(fid)
            entries.append(CatalogEntry(
                file_id=fid,
                file_name=f.display_name,
                type=meta.type.value if meta else None,
                enrollment_year=meta.enrollment_year.model_dump() if meta else None,
                academic_year=meta.academic_year.model_dump() if meta else None,
                doc_description=(toc.doc_description if toc else "") or "",
                headings=f.table_of_contents or [],
            ))

        # 3. One LLM pass: relevance classification over the catalog.
        start = time.perf_counter()
        navigator = DocumentNavigator(self._gemini_navigate)
        nav_results = await navigator.navigate(query, entries, top_k=max_files)
        dur = time.perf_counter() - start
        logger.info(
            f"[Navigator] Quét catalog {len(entries)} tài liệu trong {dur:.2f}s "
            f"-> chọn {len(nav_results)}: "
            + ", ".join(f"{r['entry'].file_name}(score={r['score']}): {r['reason']}" for r in nav_results)
        )
        if not nav_results:
            return []

        # 4. Enrich selected docs with structure/artifacts; drop stale ones.
        doc_data_by_id: Dict[str, dict] = {}
        for f in files:
            fid = str(f.id)
            toc = toc_map.get(fid)
            doc_data_by_id[fid] = {
                "storage_path": f.storage_path or "",
                "markdown_storage_path": (toc.markdown_storage_path if toc else "") or "",
                "table_of_contents": f.table_of_contents or [],
                "doc_description": (toc.doc_description if toc else "") or "",
                "structure": serialize_toc_structure(toc.structure) if toc else [],
            }

        return build_candidate_files(nav_results, doc_data_by_id)

    @staticmethod
    def _metadata_conditions(metadata_filter: Optional[dict]) -> list[dict]:
        """
        Điều kiện Mongo cho lọc metadata (Stage 1 pruning, áp ở mức file).
        File KHÔNG có metadata năm vẫn được giữ (áp dụng chung mọi khóa);
        file có năm nhưng không giao với filter thì bị loại.
        """
        conds: list[dict] = []
        for dim in ("enrollment_year", "academic_year"):
            yr = (metadata_filter or {}).get(dim)
            if not yr:
                continue
            lo = yr.get("from_year") or 0
            hi = yr.get("to_year") or 9999
            conds.append({"$or": [
                {f"custom_metadata.{dim}": None},
                {
                    f"custom_metadata.{dim}.from_year": {"$lte": hi},
                    f"custom_metadata.{dim}.to_year": {"$gte": lo},
                },
            ]})
        return conds

    async def enrich_corpus_candidates(
        self,
        candidates: list,  # list of Candidate dataclass instances from corpus.dtos.traversal
        metadata_filter: Optional[dict] = None,
        max_files: int = 5,
        user_role: Optional[str] = None,
    ) -> list[dict]:
        """
        Convert corpus TraversalResult.file_candidates to candidate_files format
        expected by run_agent_loop.
        Looks up FileDocument (status=ready) and FileTocTree for each candidate.
        Áp metadata_filter (khóa/năm học) trực tiếp bằng Mongo query.
        Student role không thấy file lecturer_only (đồng bộ với file_router).
        Drops candidates where storage paths are missing.
        Giữ thứ tự candidates từ traversal, cắt tại max_files sau khi lọc.
        """
        from bson import ObjectId

        if not candidates:
            return []

        id_order = [c.leaf_id for c in candidates]
        valid_ids = []
        for c in candidates:
            try:
                valid_ids.append(ObjectId(c.leaf_id))
            except Exception:
                pass

        if not valid_ids:
            return []

        query: dict = {"_id": {"$in": valid_ids}, "status": FileStatus.READY.value}
        if user_role == "student":
            query["lecturer_only"] = {"$ne": True}
        meta_conds = self._metadata_conditions(metadata_filter)
        if meta_conds:
            query["$and"] = meta_conds

        files, _ = await self._file_repo.list_files(
            query,
            skip=0,
            limit=len(valid_ids) + 1,
        )
        if not files:
            return []

        file_ids_str = [str(f.id) for f in files]
        toc_docs = await self._toc_repo.find_by_file_ids(file_ids_str)
        toc_map = {t.file_id: t for t in toc_docs}

        result = []
        for f in files:
            fid = str(f.id)
            toc = toc_map.get(fid)
            storage_path = f.storage_path or ""
            markdown_storage_path = (toc.markdown_storage_path if toc else "") or ""
            if not storage_path or not markdown_storage_path:
                continue
            result.append({
                "file_id": fid,
                "file_name": f.display_name or "",
                "nav_reason": "corpus_traversal",
                "doc_description": (toc.doc_description if toc else "") or "",
                "structure": serialize_toc_structure(toc.structure) if toc else [],
                "markdown_storage_path": markdown_storage_path,
                "storage_path": storage_path,
                "table_of_contents": f.table_of_contents or [],
            })

        # Giữ thứ tự candidates từ traversal (ổn định), cắt tại max_files
        order = {fid: i for i, fid in enumerate(id_order)}
        result.sort(key=lambda x: order.get(x["file_id"], len(order)))
        dropped = len(candidates) - len(result)
        result = result[:max_files]
        logger.info(
            f"[Corpus] enrich_corpus_candidates: {len(result)} enriched, "
            f"{dropped} dropped (filtered/missing storage_path)"
        )
        return result


_retrieval_service_instance: Optional[RetrievalService] = None

def get_retrieval_service() -> RetrievalService:
    global _retrieval_service_instance
    if _retrieval_service_instance is None:
        _retrieval_service_instance = RetrievalService()
    return _retrieval_service_instance
