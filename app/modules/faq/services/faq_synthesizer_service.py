import logging
import uuid
import asyncio
import numpy as np
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone, timedelta

from app.core.config import settings
from app.integrations.llm.gateway import LLMGateway, get_llm_gateway
from app.integrations.llm.prompts import render_messages
from app.utils.format_utils import markdown_to_rich_text
from app.modules.faq.repositories.interaction_log_repository import InteractionLogRepository
from app.modules.faq.repositories.faq_candidate_repository import FaqCandidateRepository
from app.utils.text_utils import remove_accents
from app.utils.json_utils import parse_json_safely
from app.modules.metadata.services.metadata_service import get_metadata_service
from app.modules.metadata.models.value_objects import FaqMetadata, YEAR_MIN, YEAR_MAX
from app.modules.faq.models.faq import FaqDocument
from app.modules.faq.models.faq_candidate import FaqCandidateDocument
from app.modules.faq.models.interaction_log import InteractionLogDocument
from app.modules.faq.services.faq_service import get_faq_service

logger = logging.getLogger(__name__)

SYSTEM_TEXT = """You synthesize high-quality university academic-affairs FAQs from clusters of similar student questions and the corresponding system answers.

Using the supplied cluster data:
1. Create one clear, concise Vietnamese 'question' that captures the shared core intent of the cluster.
2. Create one comprehensive Vietnamese 'answer_draft' derived only from the supplied system answers. Use readable Markdown when useful, including emphasis and lists, and preserve factual accuracy.
3. Infer an applicable 'metadata_filter_suggestion' containing academic_year and enrollment_year. Use null when the answer applies generally.

Return JSON with exactly these keys:
{{
    "question": "Synthesized Vietnamese question",
    "answer_draft": "Synthesized Vietnamese answer",
    "metadata_filter_suggestion": {{
        "academic_year": {{ "from_year": 2024, "to_year": 2025 }},
        "enrollment_year": {{ "from_year": 2020, "to_year": {YEAR_MAX} }}
    }}
}}""".replace("{YEAR_MAX}", str(YEAR_MAX))

# Prompt for the LLM gateway to synthesize FAQ
SYNTHESIS_PROMPT = [
    ("system", SYSTEM_TEXT),
    ("user", "Recent system FAQs for style and content consistency:\n{recent_faqs}\n\nCluster data:\n{cluster_data}"),
]


class FaqSynthesisService:
    def __init__(self, llm_gateway: LLMGateway | None = None):
        self._log_repo = InteractionLogRepository()
        self._candidate_repo = FaqCandidateRepository()
        self._llm_gateway = llm_gateway or get_llm_gateway()

    def _cosine_similarity(self, v1: List[float], v2: List[float]) -> float:
        """Calculate cosine similarity between two vectors."""
        vec1 = np.array(v1)
        vec2 = np.array(v2)
        dot_product = np.dot(vec1, vec2)
        norm1 = np.linalg.norm(vec1)
        norm2 = np.linalg.norm(vec2)
        if norm1 == 0 or norm2 == 0:
            return 0.0
        return float(dot_product / (norm1 * norm2))

    def _greedy_clustering(
        self,
        logs: List[InteractionLogDocument],
        threshold: float = 0.85,
    ) -> List[List[InteractionLogDocument]]:
        """
        Group logs into clusters using greedy cosine similarity.
        Assumes vectors are already available in the logs.
        """
        clusters = []
        unassigned = list(logs)

        while unassigned:
            # Pop the first unassigned log as the seed for a new cluster
            seed = unassigned.pop(0)
            current_cluster = [seed]
            seed_vector = seed.question_vector
            
            if not seed_vector:
                # If no vector, it stays in its own cluster of size 1
                clusters.append(current_cluster)
                continue

            next_unassigned = []
            for candidate in unassigned:
                candidate_vector = candidate.question_vector
                
                if not candidate_vector:
                    next_unassigned.append(candidate)
                    continue
                    
                sim = self._cosine_similarity(seed_vector, candidate_vector)
                if sim >= threshold:
                    current_cluster.append(candidate)
                else:
                    next_unassigned.append(candidate)
            
            unassigned = next_unassigned
            clusters.append(current_cluster)

        return clusters

    def _group_by_metadata(self, logs: List[InteractionLogDocument]) -> Dict[str, List[InteractionLogDocument]]:
        """Group logs by their metadata footprint and source type."""
        groups = {}
        for log in logs:
            meta = log.metadata_filter.model_dump() if log.metadata_filter else {}
            _, _, meta_model = get_metadata_service().validate_and_parse_faq_metadata(meta)
            
            if meta_model:
                ay = f"{meta_model.academic_year.from_year}-{meta_model.academic_year.to_year}"
                ey = f"{meta_model.enrollment_year.from_year}-{meta_model.enrollment_year.to_year}"
            else:
                ay = f"{YEAR_MIN}-{YEAR_MAX}"
                ey = f"{YEAR_MIN}-{YEAR_MAX}"
                
            source = log.source_type or "unknown"
            
            key = f"{source}|ay:{ay}|ey:{ey}"
            if key not in groups:
                groups[key] = []
            groups[key].append(log)
            
        return groups

    async def _synthesize_cluster(
        self,
        cluster: List[InteractionLogDocument],
        batch_id: str,
        recent_faqs: List[FaqDocument],
    ) -> Optional[FaqCandidateDocument]:
        """Call LLM to synthesize a candidate from a cluster."""
        source_type = cluster[0].source_type or "mixed"
        
        # Prepare context for LLM
        # Limit to top 10 diverse examples to save context window
        sample_logs = cluster[:10]
        cluster_text = ""
        for idx, log in enumerate(sample_logs):
            cluster_text += f"--- Example {idx+1} ---\n"
            cluster_text += f"Q: {log.question}\n"
            cluster_text += f"A: {log.answer_markdown}\n"
            meta = log.metadata_filter.model_dump() if log.metadata_filter else {}
            if meta:
                cluster_text += f"Meta: {meta}\n"
            cluster_text += "\n"

        recent_faqs_text = ""
        if recent_faqs:
            for idx, faq in enumerate(recent_faqs):
                recent_faqs_text += f"FAQ {idx+1}:\nQ: {faq.question}\nA: {faq.answer_markdown}\n\n"
        else:
            recent_faqs_text = "No existing FAQs are available.\n\n"

        try:
            messages = render_messages(
                SYNTHESIS_PROMPT,
                recent_faqs=recent_faqs_text,
                cluster_data=cluster_text,
            )
            response = await self._llm_gateway.complete(
                messages=messages,
                model=settings.LLM_MODEL,
                temperature=settings.LLM_DETERMINISTIC_TEMPERATURE,
                response_format={"type": "json_object"},
            )
            result = parse_json_safely(response.text or "")
            
            if not result or "question" not in result or "answer_draft" not in result:
                logger.warning(f"Failed to synthesize cluster {batch_id}. Invalid LLM output.")
                return None
                
            now = datetime.now(timezone.utc)
            answer_draft_md = result["answer_draft"]
            is_valid, errors, meta_model = get_metadata_service().validate_and_parse_faq_metadata(
                result.get("metadata_filter_suggestion", {}) or {}
            )
            if not is_valid:
                logger.warning(
                    f"LLM suggested invalid FAQ metadata: {', '.join(errors)}. "
                    f"Rejecting synthesis for batch {batch_id}."
                )
                return None

            candidate = FaqCandidateDocument(
                question=result["question"],
                question_unaccented=remove_accents(result["question"]),
                answer_draft_markdown=answer_draft_md,
                answer_draft_rich_text=markdown_to_rich_text(answer_draft_md),
                answer_draft_unaccented=remove_accents(answer_draft_md),
                metadata_filter_suggestion=meta_model or FaqMetadata(),
                source_type=source_type,
                source_log_ids=[str(log.id) for log in cluster],
                similar_count=len(cluster),
                status="pending",
                synthesis_batch_id=batch_id,
                created_at=now,
                updated_at=now,
            )
            return candidate
            
        except Exception as e:
            logger.error("Error during LLM synthesis: %s", e, exc_info=True)
            return None

    async def run(self, date_from_str: Optional[str] = None, date_to_str: Optional[str] = None, sources: Optional[List[str]] = None) -> Dict[str, Any]:
        """Main entry point to run the synthesis workflow."""
        now = datetime.now(timezone.utc)
        
        if date_to_str:
            date_to = datetime.fromisoformat(date_to_str.replace("Z", "+00:00"))
        else:
            date_to = now
            
        if date_from_str:
            date_from = datetime.fromisoformat(date_from_str.replace("Z", "+00:00"))
        else:
            date_from = date_to - timedelta(days=settings.FAQ_SYNTHESIS_LOOKBACK_DAYS)
            
        sources = sources or ["chat", "inquiry_email"]
        batch_id = f"batch_{now.strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:6]}"
        
        logger.info(f"Starting FAQ Synthesis {batch_id} from {date_from} to {date_to} for sources {sources}")
        
        # 1. Fetch Logs
        logs = await self._log_repo.find_for_synthesis(date_from, date_to, sources)
        total_logs = len(logs)
        logger.info(f"Fetched {total_logs} interaction logs.")
        
        if total_logs == 0:
            return {"batch_id": batch_id, "candidates_created": 0, "total_logs_processed": 0, "clusters_found": 0, "failed_clusters": 0}

        # Fetch top 5 recent FAQs for context
        faq_svc = await get_faq_service()
        recent_faqs_res = await faq_svc.list_faqs(limit=5)
        recent_faqs = recent_faqs_res.items

        # 2. Group by Metadata & Source
        groups = self._group_by_metadata(logs)
        logger.info(f"Grouped into {len(groups)} distinct metadata/source buckets.")
        
        total_clusters = 0
        candidates_created = 0
        failed_clusters = 0
        
        # 3. Cluster within groups
        for group_key, group_logs in groups.items():
            if len(group_logs) < settings.FAQ_SYNTHESIS_MIN_CLUSTER_SIZE:
                logger.info(
                    f"Skipping bucket '{group_key}': contains {len(group_logs)} logs, "
                    f"which is less than FAQ_SYNTHESIS_MIN_CLUSTER_SIZE ({settings.FAQ_SYNTHESIS_MIN_CLUSTER_SIZE})."
                )
                continue
                
            logger.info(f"Clustering bucket '{group_key}' with {len(group_logs)} logs...")
            clusters = await asyncio.to_thread(
                self._greedy_clustering, group_logs, settings.FAQ_SYNTHESIS_CLUSTERING_THRESHOLD
            )
            logger.info(f"Bucket '{group_key}': found {len(clusters)} clusters.")
            
            # 4. Filter and Synthesize
            for c_idx, cluster in enumerate(clusters):
                if len(cluster) >= settings.FAQ_SYNTHESIS_MIN_CLUSTER_SIZE:
                    total_clusters += 1
                    logger.info(
                        f"Synthesizing cluster {c_idx+1} of bucket '{group_key}' "
                        f"with {len(cluster)} similar logs..."
                    )
                    candidate_doc = await self._synthesize_cluster(cluster, batch_id, recent_faqs)
                    if candidate_doc:
                        await self._candidate_repo.create(candidate_doc)
                        candidates_created += 1
                        logger.info(f"Successfully created FAQ Candidate: '{candidate_doc.question}'")
                    else:
                        failed_clusters += 1
                        logger.warning(f"Failed to synthesize cluster {c_idx+1} of bucket '{group_key}'.")
                else:
                    logger.info(
                        f"Skipping cluster {c_idx+1} of bucket '{group_key}': "
                        f"size {len(cluster)} is less than FAQ_SYNTHESIS_MIN_CLUSTER_SIZE ({settings.FAQ_SYNTHESIS_MIN_CLUSTER_SIZE})."
                    )

        logger.info(
            f"Synthesis {batch_id} complete. Created {candidates_created} candidates "
            f"from {total_clusters} valid clusters. Failed: {failed_clusters}"
        )
        
        return {
            "batch_id": batch_id,
            "candidates_created": candidates_created,
            "total_logs_processed": total_logs,
            "clusters_found": total_clusters,
            "failed_clusters": failed_clusters
        }


_synthesis_service_instance: Optional[FaqSynthesisService] = None
_synthesis_lock = asyncio.Lock()

async def get_faq_synthesis_service() -> FaqSynthesisService:
    global _synthesis_service_instance
    if _synthesis_service_instance is None:
        async with _synthesis_lock:
            if _synthesis_service_instance is None:
                _synthesis_service_instance = FaqSynthesisService()
    return _synthesis_service_instance
