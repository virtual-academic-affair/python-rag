"""
FAQ hydration for RAG retrieval.

FAQ được hydrate để pipeline kiểm tra trả lời trực tiếp trước. Nếu không đủ khớp,
FAQ tiếp tục được nhồi vào prompt như ngữ cảnh bổ trợ cho PageIndex agent.
"""
from __future__ import annotations
import logging

from app.modules.faq.services.faq_service import get_faq_service

logger = logging.getLogger(__name__)


async def fetch_supporting_faqs(supporting_faqs: list, limit: int = 3) -> list:
    """
    Fetch FaqDocument cho các Candidate(kind='faq') từ traversal.
    Corpus prefilter đã lọc FAQ active trước traversal; ở đây chỉ hydrate theo ID
    và giữ thứ tự ưu tiên từ traversal. Best-effort: FAQ lỗi/không tồn tại thì bỏ qua.
    """
    if not supporting_faqs:
        return []

    valid_ids = []
    for cand in supporting_faqs[:limit]:
        if cand.leaf_id:
            valid_ids.append(cand.leaf_id)

    if not valid_ids:
        return []

    try:
        faq_svc = await get_faq_service()
        faqs = await faq_svc.get_faqs_by_ids(valid_ids)
    except Exception as e:
        logger.warning("[FAQ] Failed to hydrate supporting FAQs: %s", e)
        return []

    faq_map = {str(faq.id): faq for faq in faqs}
    faq_docs = []
    for cand in supporting_faqs[:limit]:
        faq = faq_map.get(cand.leaf_id)
        if faq:
            faq_docs.append(faq)

    return faq_docs


def build_faq_context(faq_docs: list) -> str:
    """Dựng khối ngữ cảnh FAQ để nhồi vào prompt PageIndex khi FAQ không đủ trả lời trực tiếp."""
    if not faq_docs:
        return ""
    faq_parts = [
        f"**Câu hỏi liên quan:** {f.question}\n**Trả lời tham khảo:** {f.answer_markdown}"
        for f in faq_docs
    ]
    return (
        "## Ngữ cảnh bổ sung từ FAQ (tham khảo khi cần đọc thêm tài liệu):\n\n"
        + "\n\n---\n\n".join(faq_parts)
        + "\n\n"
    )
