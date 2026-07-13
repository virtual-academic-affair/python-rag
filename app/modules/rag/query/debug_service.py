from __future__ import annotations

from app.modules.chat.utils import simplify_step
from app.modules.rag.query import RagQueryInput, get_rag_query_pipeline
from app.modules.rag.query.dtos import RagChatPreviewRequest, RagChatPreviewResponse


class RagDebugService:
    async def chat_preview(self, body: RagChatPreviewRequest) -> RagChatPreviewResponse:
        result = await get_rag_query_pipeline().answer_chat(
            RagQueryInput(
                mode="chat",
                question=body.question,
                user_role=body.role,
                user_name="Debug Preview",
                enrollment_year=body.enrollment_year,
            )
        )
        steps = [simplify_step(step, result.candidate_files) for step in result.steps]
        return RagChatPreviewResponse.from_result(result, role=body.role, steps=steps)


_rag_debug_service_instance: RagDebugService | None = None


def get_rag_debug_service() -> RagDebugService:
    global _rag_debug_service_instance
    if _rag_debug_service_instance is None:
        _rag_debug_service_instance = RagDebugService()
    return _rag_debug_service_instance
