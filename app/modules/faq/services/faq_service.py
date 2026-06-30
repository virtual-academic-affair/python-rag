from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from google.genai import types
from pymongo.errors import DuplicateKeyError

from app.core.config import settings
from app.core.exceptions import ValidationException, ConflictException
from app.core.pagination import PagedResult
from app.integrations.llm.gemini import gemini_client
from app.modules.faq.dtos.create_faq import FaqBulkCreateItem
from app.modules.faq.models.faq import FaqDocument
from app.modules.faq.models.faq_candidate import FaqCandidateDocument
from app.modules.faq.repositories.faq_candidate_repository import FaqCandidateRepository
from app.modules.faq.repositories.faq_repository import FaqRepository
from app.modules.faq.repositories.interaction_log_repository import InteractionLogRepository
from app.modules.faq.services.faq_matcher import FaqMatchEntry, FaqMatcher
from app.modules.metadata.models.value_objects import FaqMetadata
from app.modules.metadata.services.metadata_service import get_metadata_service
from app.modules.metadata.utils.filter_builder import get_filter_builder
from app.utils.format_utils import markdown_to_rich_text, rich_text_to_markdown
from app.utils.retry import async_retry
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
    # LLM adapter
    # ------------------------------------------------------------------

    async def _gemini_match(self, prompt: str) -> str:
        """Adapter: run the FAQ matcher prompt through Gemini, return raw JSON text."""
        model = settings.FAQ_MATCHER_MODEL or settings.GEMINI_MODEL
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
            metadata_filter=metadata_model,
            source=source,
            candidate_id=candidate_id,
            is_active=True,
            view_count=0,
        )
        try:
            created = await self._faq_repo.create(doc)
            # Corpus graph index — best-effort
            try:
                from app.modules.corpus.services.corpus_index_service import get_corpus_index_service
                await get_corpus_index_service().index_faq(str(created.id), metadata_model.model_dump(mode="json"))
            except Exception as _corpus_err:
                logger.warning(f"[Corpus] index_faq skipped for {created.id}: {_corpus_err}")
            return created
        except DuplicateKeyError:
            raise ConflictException(f"FAQ with question '{question}' already exists.")

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

        if "is_active" in data:
            doc.is_active = data["is_active"]

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
            # Re-index in corpus — best-effort
            try:
                from app.modules.corpus.services.corpus_index_service import get_corpus_index_service
                await get_corpus_index_service().index_faq(faq_id, saved.metadata_filter.model_dump(mode="json"))
            except Exception as _corpus_err:
                logger.warning(f"[Corpus] re-index faq skipped for {faq_id}: {_corpus_err}")
            return saved
        except DuplicateKeyError:
            raise ConflictException(f"FAQ with question '{doc.question}' already exists.")

    async def delete_faq(self, faq_id: str) -> bool:
        doc = await self._faq_repo.find_by_id(faq_id)
        if not doc:
            return False
        # Corpus graph unindex — best-effort
        try:
            from app.modules.corpus.services.corpus_index_service import get_corpus_index_service
            await get_corpus_index_service().unindex_faq(faq_id)
        except Exception as _corpus_err:
            logger.warning(f"[Corpus] unindex_faq skipped for {faq_id}: {_corpus_err}")
        await self._faq_repo.delete(doc)
        return True

    async def get_faq(self, faq_id: str) -> Optional[FaqDocument]:
        return await self._faq_repo.find_by_id(faq_id)

    async def list_faqs(
        self,
        is_active: Optional[bool] = None,
        metadata_filter: Optional[Dict[str, Any]] = None,
        search: Optional[str] = None,
        page: int = 1,
        limit: int = 20,
    ) -> PagedResult[FaqDocument]:
        mongo_filter = None
        if metadata_filter:
            builder = get_filter_builder()
            mongo_filter = await builder.build_mongo_filter(metadata_filter, mongo_prefix="metadata_filter")

        items, total = await self._faq_repo.list_faqs(
            is_active=is_active,
            metadata_filter=mongo_filter,
            search_text=remove_accents(search) if search else None,
            skip=(page - 1) * limit,
            limit=limit,
        )
        return PagedResult(items=items, total=total, page=page, limit=limit)

    # ------------------------------------------------------------------
    # Vectorless FAQ matching
    # ------------------------------------------------------------------

    async def find_best_match(
        self,
        question: str,
        metadata_filter: Dict[str, Any],
        threshold: Optional[float] = None,
        top_k: int = 5,
    ) -> Optional[FaqDocument]:
        """Find the best matching active FAQ for *question* via one LLM pass.

        Replaces Qdrant cosine similarity search. Flow:
        1. MongoDB query: fetch active FAQs filtered by metadata (the "folder" layer).
        2. Build a compact catalog of FAQ questions.
        3. One LLM call: relevance classification → best match or null.
        4. Return the matching FaqDocument (or None) and bump view_count.
        """
        # 1. Build metadata-based MongoDB filter
        mongo_filter: Optional[dict] = None
        if metadata_filter:
            builder = get_filter_builder()
            mongo_filter = await builder.build_mongo_filter(
                metadata_filter, mongo_prefix="metadata_filter"
            )

        faqs, _ = await self._faq_repo.list_faqs(
            is_active=True,
            metadata_filter=mongo_filter,
            skip=0,
            limit=settings.FAQ_MATCHER_MAX_CATALOG,
        )
        if not faqs:
            logger.info(f"[FAQ] No active FAQs in catalog for metadata {metadata_filter}")
            return None

        # 2. Build catalog entries
        entries: List[FaqMatchEntry] = []
        faq_by_index: Dict[int, FaqDocument] = {}
        for i, faq in enumerate(faqs, 1):
            meta = faq.metadata_filter
            ey = meta.enrollment_year.model_dump() if meta.enrollment_year else None
            ay = meta.academic_year.model_dump() if meta.academic_year else None
            entries.append(FaqMatchEntry(
                faq_id=str(faq.id),
                question=faq.question,
                enrollment_year=ey,
                academic_year=ay,
            ))
            faq_by_index[i] = faq

        # 3. One LLM pass
        matcher = FaqMatcher(self._gemini_match)
        result = await matcher.match(question, entries)
        if not result:
            logger.info(f"[FAQ] LLM found no match for: '{question[:80]}'")
            return None

        matched_faq_id = result["entry"].faq_id
        matched_faq = next((f for f in faqs if str(f.id) == matched_faq_id), None)
        if not matched_faq or not matched_faq.is_active:
            return None

        logger.info(
            f"[FAQ] Match: '{matched_faq.question}' (score={result['score']}) "
            f"reason={result['reason']}"
        )
        asyncio.create_task(self._faq_repo.increment_view_count(matched_faq_id))
        return matched_faq

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
