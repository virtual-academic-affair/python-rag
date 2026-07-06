"""
FAQ Resolution — nhận supporting_faqs từ corpus traversal, fetch nội dung FAQ
và dựng khối ngữ cảnh FAQ để nhồi vào prompt Stage 4.

FAQ chỉ là ngữ cảnh bổ trợ (giống file) — KHÔNG bao giờ trả lời thẳng, để câu
trả lời luôn dựa trên tài liệu chính thức (flow.md §9).
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)


async def fetch_supporting_faqs(supporting_faqs: list, limit: int = 3) -> list:
    """
    Fetch FaqDocument cho các Candidate(kind='faq') từ traversal.
    Chỉ giữ FAQ đang active. Best-effort: FAQ lỗi/không tồn tại thì bỏ qua.
    """
    if not supporting_faqs:
        return []

    from app.modules.faq.services.faq_service import get_faq_service

    faq_svc = await get_faq_service()
    faq_docs = []
    for cand in supporting_faqs[:limit]:
        faq = await faq_svc.get_faq(cand.leaf_id)
        if faq and faq.is_active:
            faq_docs.append(faq)
    return faq_docs


def build_faq_context(faq_docs: list) -> str:
    """Dựng khối ngữ cảnh FAQ để nhồi vào prompt Stage 4 (tham khảo, không phải câu trả lời cuối)."""
    if not faq_docs:
        return ""
    faq_parts = [
        f"**Câu hỏi liên quan:** {f.question}\n**Trả lời tham khảo:** {f.answer_markdown}"
        for f in faq_docs
    ]
    return (
        "## Ngữ cảnh bổ sung từ FAQ (tham khảo, không phải câu trả lời cuối):\n\n"
        + "\n\n---\n\n".join(faq_parts)
        + "\n\n"
    )
