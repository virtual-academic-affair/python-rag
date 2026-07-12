from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pymongo.errors import DuplicateKeyError

from app.core.config import settings
from app.core.exceptions import ValidationException, ConflictException
from app.core.pagination import PagedResult
from app.modules.faq.dtos.create_faq import FaqBulkCreateItem
from app.modules.faq.models.faq import FaqDocument
from app.modules.faq.models.faq_candidate import FaqCandidateDocument
from app.modules.faq.repositories.faq_candidate_repository import FaqCandidateRepository
from app.modules.faq.repositories.faq_repository import FaqRepository
from app.modules.faq.repositories.interaction_log_repository import InteractionLogRepository
from app.modules.rag.query.answering.faq_answering import FaqAnswerService
from app.modules.metadata.models.value_objects import FaqMetadata
from app.modules.metadata.services.metadata_service import get_metadata_service
from app.modules.metadata.utils.filter_builder import get_filter_builder
from app.modules.corpus.utils.prefilter import build_faq_prefilter_query
from app.modules.rag.ingestion.corpus_linker import get_corpus_linker
from app.utils.format_utils import markdown_to_rich_text, rich_text_to_markdown
from app.utils.text_utils import remove_accents


logger = logging.getLogger(__name__)

_faq_service_instance: Optional["FaqService"] = None
_faq_service_lock = asyncio.Lock()


class FaqService:
    def __init__(self):
        self._faq_repo = FaqRepository()
        self._candidate_repo = FaqCandidateRepository()
        self._log_repo = InteractionLogRepository()

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    async def create_faq(
        self,
        question: str,
        answer_rich_text: str,
        metadata_filter: Dict[str, Any],
        source: str = "manual",
        candidate_id: Optional[str] = None,
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
            candidate_id=candidate_id,
            is_active=True,
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

        # Keep original fields for rollback
        original_fields = {
            "is_active": doc.is_active,
            "lecturer_only": doc.lecturer_only,
            "question": doc.question,
            "question_unaccented": doc.question_unaccented,
            "answer_markdown": doc.answer_markdown,
            "answer_rich_text": doc.answer_rich_text,
            "answer_unaccented": doc.answer_unaccented,
            "metadata_filter": doc.metadata_filter.model_copy() if doc.metadata_filter else None
        }

        if "is_active" in data:
            doc.is_active = data["is_active"]

        if data.get("lecturer_only") is not None:
            doc.lecturer_only = data["lecturer_only"]

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
            doc.metadata_filter = meta_model or FaqMetadata()

        try:
            saved = await self._faq_repo.save(doc)
        except DuplicateKeyError:
            raise ConflictException(f"FAQ with question '{doc.question}' already exists.")

        # Determine index actions
        needs_unindex = data.get("is_active") is False or (doc.is_active is False and "is_active" not in data)
        needs_reindex = doc.is_active and (
            "question" in data
            or "answer_rich_text" in data
            or "answer_markdown" in data
            or "metadata_filter" in data
            or data.get("is_active") is True
        )

        try:
            if needs_unindex:
                await get_corpus_linker().unindex_faq(faq_id)
            elif needs_reindex:
                corpus_linker = get_corpus_linker()

                node_keys = await corpus_linker.index_faq(
                    faq_id,
                    question=saved.question or "",
                    answer_markdown=saved.answer_markdown or "",
                )
                if not node_keys:
                    raise ValueError("LLM could not assign the FAQ to any node in the corpus catalog.")
        except Exception as e:
            # Rollback MongoDB fields
            for k, v in original_fields.items():
                setattr(doc, k, v)
            await self._faq_repo.save(doc)
            # Best-effort: restore corpus tree to old state using original question/answer
            try:
                await get_corpus_linker().index_faq(
                    faq_id,
                    question=original_fields.get("question", "") or "",
                    answer_markdown=original_fields.get("answer_markdown", "") or "",
                )
            except Exception:
                pass  # corpus state may be inconsistent; backfill can fix later
            raise e

        return saved

    async def delete_faq(self, faq_id: str) -> bool:
        doc = await self._faq_repo.find_by_id(faq_id)
        if not doc:
            return False
        # Corpus tree unindex — must succeed before deletion
        await get_corpus_linker().unindex_faq(faq_id)
        await self._faq_repo.delete(doc)
        return True

    async def get_faq(self, faq_id: str) -> Optional[FaqDocument]:
        return await self._faq_repo.find_by_id(faq_id)

    async def find_ids_for_corpus(
        self,
        metadata_filter: Optional[Dict[str, Any]],
        user_role: Optional[str],
        lecturer_only: Optional[bool] = None,
    ) -> set[str]:
        """Return active FAQ IDs allowed for corpus traversal."""
        query = await build_faq_prefilter_query(metadata_filter, user_role, lecturer_only)
        return await self._faq_repo.find_ids_by_query(query)

    async def get_faqs_by_ids(self, faq_ids: List[str]) -> List[FaqDocument]:
        return await self._faq_repo.find_by_ids(faq_ids)

    async def list_faqs(
        self,
        is_active: Optional[bool] = None,
        metadata_filter: Optional[Dict[str, Any]] = None,
        search: Optional[str] = None,
        page: int = 1,
        limit: int = 20,
        exclude_lecturer_only: bool = False,
    ) -> PagedResult[FaqDocument]:
        mongo_filter = None
        if metadata_filter:
            builder = get_filter_builder()
            mongo_filter = await builder.build_mongo_filter(metadata_filter, mongo_prefix="metadata_filter")
        if exclude_lecturer_only:
            mongo_filter = {**(mongo_filter or {}), "lecturer_only": {"$ne": True}}

        items, total = await self._faq_repo.list_faqs(
            is_active=is_active,
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
            is_active=True,
            metadata_filter=mongo_filter,
            skip=0,
            limit=settings.FAQ_MATCHER_MAX_CATALOG,
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

    # ------------------------------------------------------------------
    # Interaction logging
    # ------------------------------------------------------------------

    async def log_interaction(
        self,
        question: str,
        answer_markdown: str,
        metadata_filter: Dict[str, Any],
        source_type: str,
        processing_time_ms: int = 0,
        email_message_id: Optional[int] = None,
        # question_vector kept as ignored kwarg during transition (synthesis still reads old logs)
        question_vector: Optional[List[float]] = None,
    ) -> None:
        is_valid, errors, meta_model = get_metadata_service().validate_and_parse_faq_metadata(metadata_filter)
        if not is_valid:
            raise ValidationException(f"Invalid FAQ metadata: {', '.join(errors)}")

        await self._log_repo.log(
            question=question,
            answer_markdown=answer_markdown,
            question_vector=None,
            metadata_filter=(meta_model or FaqMetadata()).model_dump(),
            source_type=source_type,
            processing_time_ms=processing_time_ms,
            email_message_id=email_message_id,
        )

    # ------------------------------------------------------------------
    # Candidate review
    # ------------------------------------------------------------------

    async def list_candidates(
        self,
        status: Optional[str] = None,
        search: Optional[str] = None,
        page: int = 1,
        limit: int = 20,
    ) -> PagedResult[FaqCandidateDocument]:
        items, total = await self._candidate_repo.list_candidates(
            status=status,
            search_text=remove_accents(search) if search else None,
            skip=(page - 1) * limit,
            limit=limit,
        )
        return PagedResult(items=items, total=total, page=page, limit=limit)

    async def get_candidate(self, candidate_id: str) -> Optional[FaqCandidateDocument]:
        return await self._candidate_repo.find_by_id(candidate_id)

    async def review_candidate(
        self,
        candidate_id: str,
        action: str,
        reviewer_id: str,
        question_override: Optional[str] = None,
        answer_rich_text_override: Optional[str] = None,
        metadata_filter_override: Optional[Dict[str, Any]] = None,
        note: Optional[str] = None,
    ) -> FaqCandidateDocument:
        candidate = await self._candidate_repo.find_by_id(candidate_id)
        if not candidate:
            raise ValueError(f"Candidate {candidate_id} not found")

        if candidate.status != "pending":
            raise ValueError(f"Candidate {candidate_id} is already {candidate.status}")

        now = datetime.now(timezone.utc)

        if action == "approve":
            existing_faq = await self._faq_repo.find_by_candidate_id(candidate_id)
            if not existing_faq:
                final_question = question_override or candidate.question
                final_answer_rt = answer_rich_text_override or candidate.answer_draft_rich_text
                final_meta = metadata_filter_override or candidate.metadata_filter_suggestion.model_dump()

                await self.create_faq(
                    question=final_question,
                    answer_rich_text=final_answer_rt or "",
                    metadata_filter=final_meta,
                    source="synthesized",
                    candidate_id=candidate_id,
                )
            else:
                logger.info(f"[FAQ] FAQ for candidate {candidate_id} already exists. Skipping creation.")

            candidate.status = "approved"
            if question_override:
                candidate.question = question_override
                candidate.question_unaccented = remove_accents(question_override)
            if answer_rich_text_override:
                answer_md = rich_text_to_markdown(answer_rich_text_override)
                candidate.answer_draft_rich_text = answer_rich_text_override
                candidate.answer_draft_markdown = answer_md
                candidate.answer_draft_unaccented = remove_accents(answer_md)
            if metadata_filter_override:
                candidate.metadata_filter_suggestion = FaqMetadata(**metadata_filter_override)
        elif action == "reject":
            candidate.status = "rejected"
        else:
            raise ValueError("Action must be 'approve' or 'reject'")

        candidate.reviewed_by = reviewer_id
        candidate.reviewed_at = now
        candidate.review_note = note
        return await self._candidate_repo.save(candidate)


async def get_faq_service() -> FaqService:
    global _faq_service_instance
    if _faq_service_instance is None:
        async with _faq_service_lock:
            if _faq_service_instance is None:
                _faq_service_instance = FaqService()
    return _faq_service_instance
