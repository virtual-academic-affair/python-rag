"""
FAQ Resolution — Stage 3 của query workflow (Fast-Path Resolution).

Tách riêng khỏi chat service: nhận supporting_faqs từ corpus traversal,
fetch nội dung FAQ, và quyết định trả lời nhanh từ FAQ hay đi tiếp Stage 4.
"""
from __future__ import annotations
import json
import logging
from typing import Optional

from google.genai import types

from app.core.config import settings
from app.integrations.llm.gemini import gemini_client
from app.utils.retry import async_retry

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


async def try_faq_fast_path(question: str, faq_docs: list) -> Optional[str]:
    """
    Stage 3 — Fast-Path Resolution: ưu tiên trả lời từ FAQ.
    Trả về câu trả lời markdown nếu FAQ đủ thông tin, ngược lại None (→ Stage 4).
    Best-effort: mọi lỗi LLM đều fallback về None.
    """
    if not faq_docs:
        return None

    faq_block = "\n\n---\n\n".join(
        f"Câu hỏi: {f.question}\nTrả lời: {f.answer_markdown}" for f in faq_docs
    )
    prompt = (
        "Bạn là trợ lý giáo vụ đại học. Dưới đây là các cặp câu hỏi - trả lời (FAQ) đã kiểm duyệt.\n\n"
        f"FAQ:\n{faq_block}\n\n"
        f'Câu hỏi của người dùng: "{question}"\n\n'
        "Nếu các FAQ trên ĐỦ thông tin để trả lời đầy đủ và chính xác câu hỏi, "
        "hãy trả lời dựa HOÀN TOÀN trên nội dung FAQ (định dạng markdown).\n"
        "Nếu KHÔNG đủ (câu hỏi cần chi tiết hơn, khác ngữ cảnh, hoặc FAQ không liên quan), "
        "đánh dấu sufficient=false.\n\n"
        'Trả về JSON: {"sufficient": true/false, "answer": "câu trả lời markdown hoặc chuỗi rỗng"}'
    )
    try:
        resp = await async_retry(
            gemini_client.client.aio.models.generate_content,
            model=settings.FAQ_MATCHER_MODEL or settings.GEMINI_MODEL,
            contents=[prompt],
            config=types.GenerateContentConfig(
                temperature=0.0,
                response_mime_type="application/json",
            ),
        )
        data = json.loads(resp.text or "{}")
    except Exception as e:
        logger.warning(f"[FaqResolver] fast-path failed (best-effort): {e}")
        return None

    if data.get("sufficient") and data.get("answer"):
        logger.info("[FaqResolver] fast-path: sufficient — answering from FAQ")
        return data["answer"]
    logger.info("[FaqResolver] fast-path: insufficient — proceeding to document reading")
    return None
