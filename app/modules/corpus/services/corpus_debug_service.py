"""Corpus debug/preview orchestration."""

from __future__ import annotations

from app.modules.chat.utils import simplify_step
from app.modules.corpus.dtos import (
    ChatPreviewFaq,
    ChatPreviewFileCandidate,
    ChatPreviewPipelineResult,
    ChatPreviewQueryAnalysis,
    ChatPreviewRequest,
    ChatPreviewResponse,
    ChatPreviewStep,
    CorpusMetadataFilterResponse,
    CorpusPrefilterResponse,
    FaqCandidateResponse,
    FileCandidateResponse,
    TopicSelectionResponse,
    TraversalTokenUsageResponse,
    TraverseRequest,
    TraverseResponse,
)
from app.modules.rag.query import RagQueryInput, get_rag_query_pipeline
from app.modules.rag.query.retrieval.traversal import run_corpus_traversal_pipeline


class CorpusDebugService:
    async def traverse(self, body: TraverseRequest) -> TraverseResponse:
        metadata_filter = body.normalized_metadata_filter()
        result = await run_corpus_traversal_pipeline(
            body.question,
            metadata_filter=metadata_filter or None,
            user_role=body.role,
        )
        return TraverseResponse(
            query=body.question,
            role=body.role,
            metadata_filter=CorpusMetadataFilterResponse.from_filter(metadata_filter),
            prefilter=CorpusPrefilterResponse.from_trace(result.prefilter),
            traversal_node_keys=result.traversal_node_keys,
            status=result.status,
            selected_topics=[
                TopicSelectionResponse(
                    node_key=selection.node_key,
                    node_title=selection.node_title,
                    scope=selection.scope,
                )
                for selection in result.selected_topics
            ],
            expanded_node_keys=result.traversal_node_keys,
            inspected_node_keys=result.inspected_node_keys,
            termination_reason=result.termination_reason,
            turn_count=result.turn_count,
            token_usage=(TraversalTokenUsageResponse(**result.token_usage) if result.token_usage else None),
            file_candidates=[
                FileCandidateResponse(
                    file_id=candidate.file_id,
                    node_key=candidate.node_key,
                    node_title=candidate.node_title,
                )
                for candidate in result.file_candidates
            ],
            faq_candidates=[
                FaqCandidateResponse(
                    faq_id=candidate.faq_id,
                    node_key=candidate.node_key,
                    node_title=candidate.node_title,
                )
                for candidate in result.faq_candidates
            ],
            total_file_candidates=len(result.file_candidates),
            total_faq_candidates=len(result.faq_candidates),
        )

    async def chat_preview(self, body: ChatPreviewRequest) -> ChatPreviewResponse:
        result = await get_rag_query_pipeline().answer_chat(
            RagQueryInput(
                mode="chat",
                question=body.question,
                user_role=body.role,
                user_name="Debug Preview",
                enrollment_year=body.enrollment_year,
            )
        )
        analysis = result.analysis
        simplified_steps = [simplify_step(step, result.candidate_files) for step in result.steps]
        return ChatPreviewResponse(
            query_analysis=ChatPreviewQueryAnalysis.from_step(analysis.as_step() if analysis else None),
            pipeline_result=ChatPreviewPipelineResult(
                source=result.source,
                max_turns_reached=result.max_turns_reached,
                role_used_for_filtering=body.role,
                file_candidates=[
                    ChatPreviewFileCandidate(
                        file_id=candidate["file_id"],
                        file_name=candidate["file_name"],
                    )
                    for candidate in result.candidate_files
                ],
                faq_docs=[
                    ChatPreviewFaq(question=faq.question, is_active=faq.is_active)
                    for faq in result.faq_docs
                ],
                sources=result.sources,
                steps=[
                    ChatPreviewStep(type=step.get("type", ""), content=step.get("content", ""))
                    for step in simplified_steps
                ],
            ),
        )


_corpus_debug_service_instance: CorpusDebugService | None = None


def get_corpus_debug_service() -> CorpusDebugService:
    global _corpus_debug_service_instance
    if _corpus_debug_service_instance is None:
        _corpus_debug_service_instance = CorpusDebugService()
    return _corpus_debug_service_instance
