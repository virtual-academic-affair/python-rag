"""
FAQ hydration for RAG retrieval.

FAQ được hydrate để pipeline kiểm tra trả lời trực tiếp trước. Nếu không đủ khớp,
FAQ tiếp tục được nhồi vào prompt như ngữ cảnh bổ trợ cho PageIndex agent.
"""
from __future__ import annotations
import logging

from app.modules.faq.services.faq_service import get_faq_service

logger = logging.getLogger(__name__)


async def hydrate_faq_candidate_docs(faq_candidates: list, limit: int = 3) -> list:
    """
    Fetch FaqDocument cho các FaqCandidate từ traversal.
    Corpus prefilter đã lọc FAQ active trước traversal; ở đây chỉ hydrate theo ID
    và giữ thứ tự ưu tiên từ traversal. Best-effort: FAQ lỗi/không tồn tại thì bỏ qua.
    """
    if not faq_candidates:
        return []

    valid_ids = []
    for cand in faq_candidates[:limit]:
        if cand.faq_id:
            valid_ids.append(cand.faq_id)

    if not valid_ids:
        return []

    try:
        faq_svc = await get_faq_service()
        faqs = await faq_svc.get_faqs_by_ids(valid_ids)
    except Exception as e:
        logger.warning("[FAQ] Failed to hydrate FAQ candidates: %s", e)
        return []

    faq_map = {str(faq.id): faq for faq in faqs}
    faq_docs = []
    for cand in faq_candidates[:limit]:
        faq = faq_map.get(cand.faq_id)
        if faq:
            faq_docs.append(faq)

    return faq_docs


def build_faq_context(faq_docs: list) -> str:
    """Dựng khối ngữ cảnh FAQ để nhồi vào prompt PageIndex khi FAQ không đủ trả lời trực tiếp."""
    if not faq_docs:
        return ""
    faq_parts = [
        f"**Related question:** {f.question}\n**Supporting answer:** {f.answer_markdown}"
        for f in faq_docs
    ]
    return (
        "## Supplemental FAQ context for document research:\n\n"
        + "\n\n---\n\n".join(faq_parts)
        + "\n\n"
    )
