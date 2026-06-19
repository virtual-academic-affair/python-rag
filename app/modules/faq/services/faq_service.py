from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.core.exceptions import ValidationException
from app.core.pagination import PagedResult
from app.modules.faq.models.faq import FaqDocument
from app.modules.faq.models.faq_candidate import FaqCandidateDocument
from app.modules.faq.repositories.faq_candidate_repository import FaqCandidateRepository
from app.modules.faq.repositories.faq_repository import FaqRepository
from app.modules.faq.repositories.interaction_log_repository import InteractionLogRepository
from app.modules.faq.services.faq_vector_service import FaqVectorService, get_faq_vector_service
from app.modules.metadata.models.value_objects import FaqMetadata
from app.modules.metadata.services.metadata_service import get_metadata_service
from app.modules.metadata.utils.filter_builder import get_filter_builder
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
        self._qdrant: Optional[FaqVectorService] = None

    async def embed(self, text: str) -> List[float]:
        return await self._qdrant.embed_question(text)

    async def create_faq(
        self,
        question: str,
        answer_rich_text: str,
        metadata_filter: Dict[str, Any],
        source: str = "manual",
        candidate_id: Optional[str] = None,
        question_vector: Optional[List[float]] = None,
    ) -> FaqDocument:
        question_unaccented = remove_accents(question)
        if not question_vector:
            question_vector = await self.embed(question)
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
            qdrant_point_id=None,
        )
        created = await self._faq_repo.create(doc)
        faq_id = str(created.id)

        try:
            qdrant_point_id = await self._qdrant.upsert_faq(
                faq_id=faq_id,
                question_vector=question_vector,
                metadata_filter=metadata_model.model_dump(),
            )
            created.qdrant_point_id = qdrant_point_id
            await self._faq_repo.save(created)
        except Exception as e:
            logger.error(
                f"[FAQ] Failed to upsert to Qdrant for FAQ {faq_id}: {e}. "
                "FAQ created in DB but not searchable via vector."
            )

        return created

    async def check_duplicate_question(self, question: str) -> Optional[FaqDocument]:
        return await self._faq_repo.find_by_unaccented_question(remove_accents(question))

    async def bulk_create_faqs(
        self,
        items: List[Dict[str, Any]],
        skip_duplicates: bool = True,
    ) -> Dict[str, Any]:
        total = len(items)
        created_count = 0
        skipped_count = 0
        failed_count = 0
        errors = []

        to_process = []
        processed_unaccented_questions = set()
        for i, item in enumerate(items):
            question = item.get("question")
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
            to_process.append((i, item))

        if not to_process:
            return {"total": total, "created": 0, "skipped": skipped_count, "failed": failed_count, "errors": errors}

        questions = [item["question"] for _, item in to_process]
        sem = asyncio.Semaphore(15)

        async def sem_embed(q: str):
            async with sem:
                return await self.embed(q)

        try:
            embeddings = await asyncio.gather(*[sem_embed(q) for q in questions])
        except Exception as e:
            logger.error(f"Failed to generate embeddings for bulk create: {e}")
            return {
                "total": total,
                "created": 0,
                "skipped": skipped_count,
                "failed": failed_count + len(to_process),
                "errors": errors + [{"question": "ALL", "error": f"Embedding failure: {str(e)}"}],
            }

        for idx, (original_idx, item) in enumerate(to_process):
            try:
                answer_rich_text = item.get("answer_rich_text") or item.get("answer")
                if not answer_rich_text:
                    raise ValueError(f"Item at row {original_idx + 1} is missing 'answer_rich_text' or 'answer' field.")

                await self.create_faq(
                    question=item["question"],
                    answer_rich_text=answer_rich_text,
                    metadata_filter=item.get("metadata_filter", {}),
                    source="bulk_import",
                    question_vector=embeddings[idx],
                )
                created_count += 1
            except Exception as e:
                logger.error(f"Failed to create FAQ in bulk at row {original_idx}: {e}")
                failed_count += 1
                errors.append({"row_index": original_idx + 1, "question": item["question"], "error": str(e)})

        return {"total": total, "created": created_count, "skipped": skipped_count, "failed": failed_count, "errors": errors}

    async def update_faq(self, faq_id: str, data: Dict[str, Any]) -> Optional[FaqDocument]:
        doc = await self._faq_repo.find_by_id(faq_id)
        if not doc:
            return None

        need_qdrant_update = False

        if "question" in data and data["question"] != doc.question:
            doc.question = data["question"]
            doc.question_unaccented = remove_accents(data["question"])
            need_qdrant_update = True

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
            need_qdrant_update = True

        if "is_active" in data:
            doc.is_active = data["is_active"]

        if need_qdrant_update:
            if "question" in data:
                question_vector = await self.embed(doc.question)
            else:
                question_vector = await self.embed(doc.question)
            await self._qdrant.upsert_faq(faq_id, question_vector, doc.metadata_filter.model_dump())

        return await self._faq_repo.save(doc)

    async def delete_faq(self, faq_id: str) -> bool:
        doc = await self._faq_repo.find_by_id(faq_id)
        if not doc:
            return False

        if doc.qdrant_point_id:
            try:
                await self._qdrant.delete_faq(doc.qdrant_point_id)
            except Exception as e:
                logger.warning(f"Failed to delete Qdrant point for FAQ {faq_id}: {e}")

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

    async def find_best_match(
        self,
        question_vector: List[float],
        metadata_filter: Dict[str, Any],
        threshold: Optional[float] = None,
    ) -> Optional[FaqDocument]:
        th = threshold or settings.FAQ_SEMANTIC_THRESHOLD
        results = await self._qdrant.search(question_vector, metadata_filter, th, top_k=1)
        if not results:
            return None

        faq_id = results[0]["faq_id"]
        faq = await self._faq_repo.find_by_id(faq_id)
        if faq and faq.is_active:
            asyncio.create_task(self._faq_repo.increment_view_count(faq_id))
            return faq

        return None

    async def log_interaction(
        self,
        question: str,
        question_vector: List[float],
        answer_markdown: str,
        metadata_filter: Dict[str, Any],
        source_type: str,
        processing_time_ms: int = 0,
        email_message_id: Optional[int] = None,
    ) -> None:
        is_valid, errors, meta_model = get_metadata_service().validate_and_parse_faq_metadata(metadata_filter)
        if not is_valid:
            raise ValidationException(f"Invalid FAQ metadata: {', '.join(errors)}")

        await self._log_repo.log(
            question=question,
            question_vector=question_vector,
            answer_markdown=answer_markdown,
            metadata_filter=(meta_model or FaqMetadata()).model_dump(),
            source_type=source_type,
            processing_time_ms=processing_time_ms,
            email_message_id=email_message_id,
        )

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
                _faq_service_instance._qdrant = await get_faq_vector_service()
    return _faq_service_instance
