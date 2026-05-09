"""
Service layer for FAQ Module.
Handles CRUD, semantic matching, and interaction logging.
"""
import logging
import asyncio
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone

from app.core.config import settings
from app.modules.faq.models import FaqDocument
from app.modules.faq.repository import FaqRepository, FaqCandidateRepository, InteractionLogRepository
from app.modules.faq.qdrant_faq import get_qdrant_faq_service, QdrantFaqService
from app.core.text_utils import remove_accents
from app.core.format_utils import markdown_to_rich_text, rich_text_to_markdown
from app.modules.metadata.service import get_metadata_service
from app.core.exceptions import ValidationException
from bson import ObjectId

logger = logging.getLogger(__name__)

_faq_service_instance: Optional['FaqService'] = None
_faq_service_lock = asyncio.Lock()


class FaqService:
    def __init__(self):
        self._faq_repo = FaqRepository()
        self._candidate_repo = FaqCandidateRepository()
        self._log_repo = InteractionLogRepository()
        self._qdrant: Optional[QdrantFaqService] = None

    async def embed(self, text: str) -> List[float]:
        """Generate embedding using QdrantFaqService."""
        return await self._qdrant.embed_question(text)

    # ==========================================
    # CRUD FAQ
    # ==========================================
    async def create_faq(
        self, 
        question: str, 
        answer_rich_text: str, 
        metadata_filter: Dict[str, Any], 
        source: str = "manual",
        candidate_id: Optional[str] = None,
        question_vector: Optional[List[float]] = None
    ) -> Dict[str, Any]:
        question_unaccented = remove_accents(question)
        if not question_vector:
            question_vector = await self.embed(question)
        answer_markdown = rich_text_to_markdown(answer_rich_text)
        
        is_valid, errors, meta_model = get_metadata_service().validate_and_parse_faq_metadata(metadata_filter)
        if not is_valid:
            raise ValidationException(f"Invalid FAQ metadata: {', '.join(errors)}")
        validated_metadata = meta_model.model_dump() if meta_model else {}

        # 1. Insert MongoDB trước (BaseRepository tự tạo timestamps)
        doc_id = ObjectId()
        doc_dict = {
            "_id": doc_id,
            "question": question,
            "question_unaccented": question_unaccented,
            "answer_unaccented": remove_accents(answer_markdown),
            "answer_markdown": answer_markdown,
            "answer_rich_text": answer_rich_text,
            "metadata_filter": validated_metadata,
            "source": source,
            "candidate_id": candidate_id,
            "is_active": True,
            "view_count": 0,
            "qdrant_point_id": None,
        }
        created = await self._faq_repo.create(doc_dict)
        faq_id_str = str(doc_id)

        # 2. Upsert to Qdrant (nếu fail, log warning — FAQ vẫn dùng được, chỉ không searchable qua vector)
        try:
            qdrant_point_id = await self._qdrant.upsert_faq(
                faq_id=faq_id_str,
                question_vector=question_vector,
                metadata_filter=validated_metadata
            )
            await self._faq_repo.update_by_id(faq_id_str, {"qdrant_point_id": qdrant_point_id})
            created["qdrant_point_id"] = qdrant_point_id
        except Exception as e:
            logger.error(f"[FAQ] Failed to upsert to Qdrant for FAQ {faq_id_str}: {e}. FAQ created in DB but not searchable via vector.")

        created["_id"] = faq_id_str
        return created

    async def check_duplicate_question(self, question: str) -> Optional[Dict[str, Any]]:
        """Check if a question (unaccented) already exists in DB."""
        unaccented = remove_accents(question)
        return await self._faq_repo.find_one({"question_unaccented": unaccented})

    async def bulk_create_faqs(
        self, 
        items: List[Dict[str, Any]], 
        skip_duplicates: bool = True
    ) -> Dict[str, Any]:
        """
        Create multiple FAQs with parallel embedding generation.
        items: List of {question, answer, metadata_filter}
        """
        total = len(items)
        created_count = 0
        skipped_count = 0
        failed_count = 0
        errors = []

        # 1. Filter out duplicates if requested
        to_process = []
        for i, item in enumerate(items):
            if skip_duplicates:
                existing = await self.check_duplicate_question(item["question"])
                if existing:
                    skipped_count += 1
                    continue
            to_process.append((i, item))

        if not to_process:
            return {
                "total": total,
                "created": 0,
                "skipped": skipped_count,
                "failed": 0,
                "errors": []
            }

        # 2. Generate embeddings in parallel
        questions = [item["question"] for _, item in to_process]
        try:
            embeddings = await asyncio.gather(*[self.embed(q) for q in questions])
        except Exception as e:
            logger.error(f"Failed to generate embeddings for bulk create: {e}")
            return {
                "total": total,
                "created": 0,
                "skipped": skipped_count,
                "failed": len(to_process),
                "errors": [{"question": "ALL", "error": f"Embedding failure: {str(e)}"}]
            }

        # 3. Create FAQs
        # Note: We could use MongoDB insert_many, but create_faq handles Qdrant too.
        # To keep it simple and reliable, we call create_faq (which is already tested).
        # Optimization: We can't easily parallelize Qdrant/Mongo without risk of race/connection limits,
        # but we already parallelized the slowest part (LLM embedding).
        
        for idx, (original_idx, item) in enumerate(to_process):
            try:
                # We already have the embedding, but create_faq will re-generate it.
                # To truly optimize, we'd refactor create_faq to accept an optional pre-computed vector.
                # For now, let's just call create_faq for safety/consistency.
                
                await self.create_faq(
                    question=item["question"],
                    answer_rich_text=item["answer_rich_text"],
                    metadata_filter=item.get("metadata_filter", {}),
                    source="bulk_import",
                    question_vector=embeddings[idx]
                )
                created_count += 1
            except Exception as e:
                logger.error(f"Failed to create FAQ in bulk at row {original_idx}: {e}")
                failed_count += 1
                errors.append({
                    "row_index": original_idx + 1, # 1-based for user friendliness
                    "question": item["question"],
                    "error": str(e)
                })

        return {
            "total": total,
            "created": created_count,
            "skipped": skipped_count,
            "failed": failed_count,
            "errors": errors
        }

    async def update_faq(self, faq_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        existing = await self._faq_repo.find_by_id(faq_id)
        if not existing:
            return None

        update_data = {}
        need_qdrant_update = False
        
        if "question" in data and data["question"] != existing.get("question"):
            update_data["question"] = data["question"]
            update_data["question_unaccented"] = remove_accents(data["question"])
            need_qdrant_update = True
            
        if "answer_rich_text" in data:
            answer_markdown = rich_text_to_markdown(data["answer_rich_text"])
            update_data["answer_markdown"] = answer_markdown
            update_data["answer_rich_text"] = data["answer_rich_text"]
            update_data["answer_unaccented"] = remove_accents(answer_markdown)
        elif "answer_markdown" in data:
            update_data["answer_markdown"] = data["answer_markdown"]
            update_data["answer_rich_text"] = markdown_to_rich_text(data["answer_markdown"])
            update_data["answer_unaccented"] = remove_accents(data["answer_markdown"])
            
        if "metadata_filter" in data:
            is_valid, errors, meta_model = get_metadata_service().validate_and_parse_faq_metadata(data["metadata_filter"])
            if not is_valid:
                raise ValidationException(f"Invalid FAQ metadata: {', '.join(errors)}")
                
            update_data["metadata_filter"] = meta_model.model_dump() if meta_model else {}
            need_qdrant_update = True
            
        if "is_active" in data:
            update_data["is_active"] = data["is_active"]
            

        if not update_data:
            return existing

        update_data["updated_at"] = datetime.now(timezone.utc)
        
        if need_qdrant_update:
            # Need to re-embed if question changed, otherwise just update payload
            if "question" in update_data:
                question_vector = await self.embed(update_data["question"])
            else:
                # We don't store vectors in MongoDB, so if we only update metadata, 
                # we technically have to re-embed or use Qdrant's update_payload.
                # For simplicity in this implementation, we re-embed if metadata changes 
                # since Qdrant upsert replaces the whole point.
                question_vector = await self.embed(existing["question"])
                
            meta = update_data.get("metadata_filter", existing.get("metadata_filter"))
            await self._qdrant.upsert_faq(faq_id, question_vector, meta)

        await self._faq_repo.update_by_id(faq_id, update_data)
        
        # Return updated document
        return await self._faq_repo.find_by_id(faq_id)

    async def delete_faq(self, faq_id: str) -> bool:
        existing = await self._faq_repo.find_by_id(faq_id)
        if not existing:
            return False
            
        point_id = existing.get("qdrant_point_id")
        if point_id:
            try:
                await self._qdrant.delete_faq(point_id)
            except Exception as e:
                logger.warning(f"Failed to delete Qdrant point for FAQ {faq_id}: {e}")
                
        return await self._faq_repo.delete_by_id(faq_id)

    async def get_faq(self, faq_id: str) -> Optional[Dict[str, Any]]:
        return await self._faq_repo.find_by_id(faq_id)

    async def list_faqs(self, is_active: Optional[bool] = None, 
                        metadata_filter: Optional[Dict[str, Any]] = None,
                        search: Optional[str] = None,
                        page: int = 1, limit: int = 20) -> Dict[str, Any]:
        
        query = {}
        if is_active is not None:
            query["is_active"] = is_active
            
        if metadata_filter:
            from app.modules.metadata.utils.filter_builder import get_filter_builder
            builder = get_filter_builder()
            mongo_filter = await builder.build_mongo_filter(metadata_filter, mongo_prefix="metadata_filter")
            query.update(mongo_filter)
            
        sort = [("created_at", -1)]
        projection = None
        if search:
            unaccented = remove_accents(search)
            query["$text"] = {"$search": unaccented}
            sort = [("score", {"$meta": "textScore"})]
            projection = {"score": {"$meta": "textScore"}}

        skip = (page - 1) * limit
        items = await self._faq_repo.find_many(query, skip=skip, limit=limit, sort=sort, projection=projection)
        total = await self._faq_repo.count(query)
        
        return {
            "items": items,
            "total": total,
            "page": page,
            "limit": limit
        }

    # ==========================================
    # Semantic Match
    # ==========================================
    async def find_best_match(
        self, 
        question_vector: List[float], 
        metadata_filter: Dict[str, Any], 
        threshold: Optional[float] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Perform semantic search in Qdrant and return the matched FAQ document.
        """
        th = threshold or settings.FAQ_SEMANTIC_THRESHOLD
        results = await self._qdrant.search(question_vector, metadata_filter, th, top_k=1)
        
        if not results:
            return None
            
        best_match = results[0]
        faq_id = best_match["faq_id"]
        
        faq = await self._faq_repo.find_by_id(faq_id)
        if faq and faq.get("is_active"):
            # Non-blocking view count increment (picked from 'another')
            asyncio.create_task(self._faq_repo.increment_view_count(faq_id))
            return faq
            
        return None

    # ==========================================
    # Interaction Logging
    # ==========================================
    async def log_interaction(
        self, 
        question: str, 
        question_vector: List[float], 
        answer_markdown: str, 
        metadata_filter: Dict[str, Any], 
        source_type: str, 
        processing_time_ms: int = 0,
        email_message_id: Optional[int] = None
    ) -> None:
        """Log an interaction to interaction_logs for later synthesis."""
        is_valid, errors, meta_model = get_metadata_service().validate_and_parse_faq_metadata(metadata_filter)
        validated_metadata = meta_model.model_dump() if meta_model else {}

        await self._log_repo.log(
            question=question,
            question_vector=question_vector,
            answer_markdown=answer_markdown,
            metadata_filter=validated_metadata,
            source_type=source_type,
            processing_time_ms=processing_time_ms,
            email_message_id=email_message_id
        )

    # ==========================================
    # Candidate Management
    # ==========================================
    async def list_candidates(self, status: Optional[str] = None, search: Optional[str] = None, page: int = 1, limit: int = 20) -> Dict[str, Any]:
        logger.info(f"Listing candidates with status='{status}', search='{search}', page={page}, limit={limit}")
        skip = (page - 1) * limit
        
        query = {}
        if status:
            query["status"] = status
        sort = [("created_at", -1)]
        projection = None
        if search:
            unaccented = remove_accents(search)
            query["$text"] = {"$search": unaccented}
            sort = [("score", {"$meta": "textScore"})]
            projection = {"score": {"$meta": "textScore"}}
            
        items = await self._candidate_repo.find_many(query, skip=skip, limit=limit, sort=sort, projection=projection)
        total = await self._candidate_repo.count(query)
        
        return {
            "items": items,
            "total": total,
            "page": page,
            "limit": limit
        }

    async def get_candidate(self, candidate_id: str) -> Optional[Dict[str, Any]]:
        return await self._candidate_repo.find_by_id(candidate_id)

    async def review_candidate(
        self, 
        candidate_id: str, 
        action: str, 
        reviewer_id: str,
        question_override: Optional[str] = None, 
        answer_rich_text_override: Optional[str] = None, 
        metadata_filter_override: Optional[Dict[str, Any]] = None,
        note: Optional[str] = None
    ) -> Dict[str, Any]:
        candidate = await self._candidate_repo.find_by_id(candidate_id)
        if not candidate:
            raise ValueError(f"Candidate {candidate_id} not found")
            
        if candidate.get("status") != "pending":
            raise ValueError(f"Candidate {candidate_id} is already {candidate.get('status')}")

        now = datetime.now(timezone.utc)
        
        if action == "approve":
            final_question = question_override or candidate["question"]
            final_answer_rt = answer_rich_text_override or candidate["answer_draft_rich_text"]
            final_meta = metadata_filter_override or candidate["metadata_filter_suggestion"]
            
            # Create the actual FAQ
            await self.create_faq(
                question=final_question,
                answer_rich_text=final_answer_rt,
                metadata_filter=final_meta,
                source="synthesized",
                candidate_id=candidate_id
            )
            
            # Update candidate
            update_fields = {
                "status": "approved",
                "reviewed_by": reviewer_id,
                "reviewed_at": now,
                "review_note": note,
                "updated_at": now
            }
            
            # Save overrides back to candidate so "All" tab shows updated info
            if question_override:
                update_fields["question"] = question_override
            if answer_rich_text_override:
                update_fields["answer_draft_rich_text"] = answer_rich_text_override
            if metadata_filter_override:
                update_fields["metadata_filter_suggestion"] = metadata_filter_override

            await self._candidate_repo.update_by_id(candidate_id, update_fields)
            
        elif action == "reject":
            await self._candidate_repo.update_by_id(candidate_id, {
                "status": "rejected",
                "reviewed_by": reviewer_id,
                "reviewed_at": now,
                "review_note": note,
                "updated_at": now
            })
        else:
            raise ValueError("Action must be 'approve' or 'reject'")
            
        return await self._candidate_repo.find_by_id(candidate_id)


async def get_faq_service() -> FaqService:
    global _faq_service_instance
    if _faq_service_instance is None:
        async with _faq_service_lock:
            if _faq_service_instance is None:
                _faq_service_instance = FaqService()
                _faq_service_instance._qdrant = await get_qdrant_faq_service()
    return _faq_service_instance
