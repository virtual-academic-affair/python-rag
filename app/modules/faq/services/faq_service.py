from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

from pymongo.errors import DuplicateKeyError

from app.core.exceptions import AppException, ValidationException, ConflictException, NotFoundException
from app.core.pagination import PagedResult
from app.modules.corpus.services.corpus_service import get_corpus_service
from app.modules.faq.dtos.create_faq import FaqBulkCreateItem
from app.modules.faq.models.faq import FaqDocument
from app.modules.faq.repositories.faq_repository import FaqRepository
from app.modules.rag.query.answering.faq_answering import FaqAnswerService
from app.modules.metadata.models.value_objects import FaqMetadata
from app.modules.metadata.services.metadata_service import get_metadata_service
from app.modules.metadata.utils.filter_builder import get_filter_builder
from app.modules.rag.ingestion.corpus_linker import get_corpus_linker
from app.modules.rag.cache import get_rag_cache_service
from app.utils.format_utils import markdown_to_rich_text, rich_text_to_markdown
from app.utils.text_utils import remove_accents


logger = logging.getLogger(__name__)

_FAQ_DEBUG_CATALOG_LIMIT = 200
_faq_service_instance: Optional["FaqService"] = None
_faq_service_lock = asyncio.Lock()


class FaqService:
    def __init__(self):
        self._faq_repo = FaqRepository()

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    async def create_faq(
        self,
        question: str,
        answer_rich_text: str,
        metadata_filter: Dict[str, Any],
        source: str = "manual",
        lecturer_only: bool = False,
        # question_vector kept as ignored kwarg for caller backward-compat during migration
        question_vector: Optional[List[float]] = None,
    ) -> FaqDocument:
        question_unaccented = remove_accents(question)
        answer_markdown = rich_text_to_markdown(answer_rich_text)

        is_valid, errors, meta_model = get_metadata_service().validate_and_parse_faq_metadata(metadata_filter)
        if not is_valid:
            raise ValidationException(f"Invalid FAQ metadata: {', '.join(errors)}")
        metadata_model = meta_model or FaqMetadata()

        doc = FaqDocument(
            question=question,
            question_unaccented=question_unaccented,
            answer_unaccented=remove_accents(answer_markdown),
            answer_markdown=answer_markdown,
            answer_rich_text=answer_rich_text,
            lecturer_only=lecturer_only,
            metadata_filter=metadata_model,
            source=source,
            view_count=0,
        )
        try:
            created = await self._faq_repo.create(doc)
        except DuplicateKeyError:
            raise ConflictException(f"FAQ with question '{question}' already exists.")

        # Index to corpus (must succeed)
        try:
            corpus_linker = get_corpus_linker()

            node_keys = await corpus_linker.index_faq(
                str(created.id),
                question=question,
                answer_markdown=answer_markdown,
            )
            if not node_keys:
                raise ValueError("LLM could not assign the FAQ to any node in the corpus catalog.")
        except Exception as e:
            # Rollback: first clean up any partial corpus links, then delete the Mongo doc
            try:
                await corpus_linker.unindex_faq(str(created.id))
            except Exception:
                pass  # best-effort cleanup; DB rollback always proceeds
            await self._faq_repo.delete(created)
            raise e

        cache = get_rag_cache_service()
        await cache.invalidate_faq(str(created.id))
        await cache.bump_faq_eligibility_revision()
        return created

    async def check_duplicate_question(self, question: str) -> Optional[FaqDocument]:
        return await self._faq_repo.find_by_unaccented_question(remove_accents(question))

    async def bulk_create_faqs(
        self,
        items: List[FaqBulkCreateItem],
        skip_duplicates: bool = True,
    ) -> Dict[str, Any]:
        total = len(items)
        created_count = 0
        skipped_count = 0
        failed_count = 0
        errors = []

        processed_unaccented_questions: set[str] = set()
        for i, item in enumerate(items):
            question = item.question
            if not question or not str(question).strip():
                failed_count += 1
                errors.append({"row_index": i + 1, "question": "", "error": "Field 'question' is missing or empty."})
                continue

            unaccented = remove_accents(str(question))
            if unaccented in processed_unaccented_questions:
                skipped_count += 1
                continue

            if skip_duplicates and await self.check_duplicate_question(question):
                skipped_count += 1
                continue

            processed_unaccented_questions.add(unaccented)

            try:
                answer_rich_text = item.answer_rich_text
                if not answer_rich_text:
                    raise ValueError(f"Item at row {i + 1} is missing 'answer_rich_text' field.")

                await self.create_faq(
                    question=item.question,
                    answer_rich_text=answer_rich_text,
                    metadata_filter=item.metadata_filter.model_dump(by_alias=False),
                    source="bulk_import",
                    lecturer_only=item.lecturer_only,
                )
                created_count += 1
            except ConflictException:
                skipped_count += 1
            except Exception as e:
                logger.error(f"Failed to create FAQ in bulk at row {i}: {e}")
                failed_count += 1
                errors.append({"row_index": i + 1, "question": item.question, "error": str(e)})

        return {"total": total, "created": created_count, "skipped": skipped_count, "failed": failed_count, "errors": errors}

    async def update_faq(self, faq_id: str, data: Dict[str, Any]) -> Optional[FaqDocument]:
        doc = await self._faq_repo.find_by_id(faq_id)
        if not doc:
            return None

        eligibility_changed = False
        if data.get("lecturer_only") is not None and data["lecturer_only"] != doc.lecturer_only:
            doc.lecturer_only = data["lecturer_only"]
            eligibility_changed = True

        if "question" in data and data["question"] != doc.question:
            doc.question = data["question"]
            doc.question_unaccented = remove_accents(data["question"])

        if "answer_rich_text" in data:
            answer_markdown = rich_text_to_markdown(data["answer_rich_text"])
            doc.answer_markdown = answer_markdown
            doc.answer_rich_text = data["answer_rich_text"]
            doc.answer_unaccented = remove_accents(answer_markdown)
        elif "answer_markdown" in data:
            doc.answer_markdown = data["answer_markdown"]
            doc.answer_rich_text = markdown_to_rich_text(data["answer_markdown"])
            doc.answer_unaccented = remove_accents(data["answer_markdown"])

        if "metadata_filter" in data:
            is_valid, errors, meta_model = get_metadata_service().merge_faq_metadata_update(
                existing=doc.metadata_filter,
                incoming_update=data["metadata_filter"] or {},
            )
            if not is_valid:
                raise ValidationException(f"Invalid merged FAQ metadata: {', '.join(errors)}")
            new_metadata = meta_model or FaqMetadata()
            if new_metadata != doc.metadata_filter:
                eligibility_changed = True
            doc.metadata_filter = new_metadata

        try:
            updated = await self._faq_repo.save(doc)
        except DuplicateKeyError:
            raise ConflictException(f"FAQ with question '{doc.question}' already exists.")
        cache = get_rag_cache_service()
        await cache.invalidate_faq(faq_id)
        if eligibility_changed:
            await cache.bump_faq_eligibility_revision()
        return updated

    async def delete_faq(self, faq_id: str, deleted_by: str) -> bool:
        doc = await self._faq_repo.find_by_id_including_deleted(faq_id)
        if not doc:
            return False

        if doc.deleted_at is None:
            node_keys = await get_corpus_service().get_payload_node_keys("faq", faq_id)
            await self._faq_repo.soft_delete(
                faq_id,
                deleted_by=deleted_by,
                corpus_node_keys=node_keys,
            )

        # Idempotent cleanup for retries after a partial failure.
        await get_corpus_linker().unindex_faq(faq_id)
        cache = get_rag_cache_service()
        await cache.invalidate_faq(faq_id)
        await cache.bump_faq_eligibility_revision()
        return True

    async def restore_faq(self, faq_id: str) -> FaqDocument:
        doc = await self._faq_repo.find_by_id_including_deleted(faq_id)
        if not doc:
            raise NotFoundException("FAQ", faq_id)
        if doc.deleted_at is None:
            raise ConflictException("FAQ is not deleted")

        duplicate = await self._faq_repo.find_by_unaccented_question(doc.question_unaccented)
        if duplicate:
            raise ConflictException(f"Active FAQ with question '{doc.question}' already exists")

        corpus_svc = get_corpus_service()
        valid_keys = await corpus_svc.existing_node_keys(doc.deleted_corpus_node_keys)
        reindexed = False
        try:
            if valid_keys:
                await corpus_svc.reindex_payload("faq", faq_id, valid_keys)
            else:
                node_keys = await get_corpus_linker().index_faq(
                    faq_id,
                    question=doc.question or "",
                    answer_markdown=doc.answer_markdown or "",
                )
                if not node_keys:
                    raise ConflictException("FAQ could not be assigned to a Corpus topic")
            reindexed = True

            if not await self._faq_repo.restore(faq_id):
                raise ConflictException("FAQ restore state changed concurrently")
        except Exception:
            if reindexed:
                await get_corpus_linker().unindex_faq(faq_id)
            raise

        restored = await self._faq_repo.find_by_id(faq_id)
        if not restored:
            raise AppException("FAQ restore completed but active record could not be loaded", status_code=500)
        cache = get_rag_cache_service()
        await cache.invalidate_faq(faq_id)
        await cache.bump_faq_eligibility_revision()
        return restored

    async def purge_faq(self, faq_id: str) -> bool:
        doc = await self._faq_repo.find_by_id_including_deleted(faq_id)
        if not doc:
            raise NotFoundException("FAQ", faq_id)
        if doc.deleted_at is None:
            raise ConflictException("FAQ must be soft-deleted before purge")
        await get_corpus_linker().unindex_faq(faq_id)
        await self._faq_repo.delete(doc)
        cache = get_rag_cache_service()
        await cache.invalidate_faq(faq_id)
        await cache.bump_faq_eligibility_revision()
        return True

    async def get_faq(self, faq_id: str) -> Optional[FaqDocument]:
        return await self._faq_repo.find_by_id(faq_id)

    async def get_faq_including_deleted(self, faq_id: str) -> Optional[FaqDocument]:
        return await self._faq_repo.find_by_id_including_deleted(faq_id)

    async def find_ids_for_corpus(
        self,
        metadata_filter: Optional[Dict[str, Any]],
        user_role: Optional[str],
        lecturer_only: Optional[bool] = None,
    ) -> set[str]:
        """Return active FAQ IDs allowed for corpus traversal."""
        query: Dict[str, Any] = {"deleted_at": None}
        privileged = (user_role or "") in {"admin", "lecture"}
        if lecturer_only is not None and privileged:
            query["lecturer_only"] = lecturer_only
        elif not privileged:
            query["lecturer_only"] = {"$ne": True}
        query.update(
            await get_filter_builder().build_mongo_filter(
                metadata_filter or {},
                mongo_prefix="metadata_filter",
            )
        )
        return await self._faq_repo.find_ids_by_query(query)

    async def get_faqs_by_ids(self, faq_ids: List[str]) -> List[FaqDocument]:
        return await self._faq_repo.find_by_ids(faq_ids)

    async def list_faqs(
        self,
        metadata_filter: Optional[Dict[str, Any]] = None,
        search: Optional[str] = None,
        page: int = 1,
        limit: int = 20,
        exclude_lecturer_only: bool = False,
        lecturer_only: Optional[bool] = None,
    ) -> PagedResult[FaqDocument]:
        mongo_filter = None
        if metadata_filter:
            builder = get_filter_builder()
            mongo_filter = await builder.build_mongo_filter(metadata_filter, mongo_prefix="metadata_filter")
        if exclude_lecturer_only:
            # Student (và role không privileged): luôn ẩn lecturer_only, kể cả khi client gửi lecturerOnly=true.
            mongo_filter = {**(mongo_filter or {}), "lecturer_only": {"$ne": True}}
        elif lecturer_only is not None:
            mongo_filter = {**(mongo_filter or {}), "lecturer_only": lecturer_only}

        items, total = await self._faq_repo.list_faqs(
            metadata_filter=mongo_filter,
            search_text=remove_accents(search) if search else None,
            skip=(page - 1) * limit,
            limit=limit,
        )
        return PagedResult(items=items, total=total, page=page, limit=limit)

    async def list_deleted_faqs(
        self,
        metadata_filter: Optional[Dict[str, Any]] = None,
        search: Optional[str] = None,
        page: int = 1,
        limit: int = 20,
        lecturer_only: Optional[bool] = None,
    ) -> PagedResult[FaqDocument]:
        mongo_filter = None
        if metadata_filter:
            mongo_filter = await get_filter_builder().build_mongo_filter(
                metadata_filter,
                mongo_prefix="metadata_filter",
            )
        if lecturer_only is not None:
            mongo_filter = {**(mongo_filter or {}), "lecturer_only": lecturer_only}
        items, total = await self._faq_repo.list_deleted_faqs(
            metadata_filter=mongo_filter,
            search_text=remove_accents(search) if search else None,
            skip=(page - 1) * limit,
            limit=limit,
        )
        return PagedResult(items=items, total=total, page=page, limit=limit)

    # ------------------------------------------------------------------
    # FAQ answer debugging
    # ------------------------------------------------------------------

    async def answer_from_faq_catalog(
        self,
        question: str,
        metadata_filter: Dict[str, Any],
        *,
        increment_view_count: bool = False,
    ):
        """Answer from active FAQs filtered by metadata via the RAG FAQ answering step.

        This is used by the admin debug endpoint; it returns the generated FAQ answer
        plus every FAQ the LLM used instead of collapsing multi-FAQ answers to one FAQ.
        """
        mongo_filter: Optional[dict] = None
        if metadata_filter:
            builder = get_filter_builder()
            mongo_filter = await builder.build_mongo_filter(
                metadata_filter, mongo_prefix="metadata_filter"
            )
        mongo_filter = {**(mongo_filter or {}), "lecturer_only": {"$ne": True}}

        faqs, _ = await self._faq_repo.list_faqs(
            metadata_filter=mongo_filter,
            skip=0,
            limit=_FAQ_DEBUG_CATALOG_LIMIT,
        )
        if not faqs:
            logger.info(f"[FAQ] No active FAQs in catalog for metadata {metadata_filter}")
            return None

        faq_answer_service = FaqAnswerService()
        faq_answer_service._faq_repo = self._faq_repo
        answer = await faq_answer_service.answer(
            question,
            faqs,
            increment_view_count=increment_view_count,
        )
        if not answer:
            logger.info(f"[FAQ] LLM found no match for: '{question[:80]}'")
            return None

        logger.info(
            "[FAQ] Answered from FAQ ids=%s",
            [str(getattr(faq, "id", "")) for faq in answer.matched_faqs],
        )
        return answer

async def get_faq_service() -> FaqService:
    global _faq_service_instance
    if _faq_service_instance is None:
        async with _faq_service_lock:
            if _faq_service_instance is None:
                _faq_service_instance = FaqService()
    return _faq_service_instance
