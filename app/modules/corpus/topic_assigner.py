from __future__ import annotations
import json
import logging
from typing import Callable, Awaitable

logger = logging.getLogger(__name__)


async def assign_topics(
    display_name: str,
    content_text: str,
    active_topics: list[tuple[str, str, str]],  # (node_key, title, summary)
    call_llm: Callable[[str], Awaitable[str]],
) -> tuple[list[str], list[dict]]:
    """
    Ask LLM to assign topic node_keys to a document/FAQ.

    Returns:
      selected_keys: node_keys from active_topics chosen by LLM
      new_topics:    genuinely new topics [{slug, title, summary}]

    If active_topics is empty, returns ([], []) without calling LLM.
    """
    if not active_topics:
        return [], []

    valid_keys = {t[0] for t in active_topics}
    catalog_lines = "\n".join(
        f"- {node_key}: {title} — {summary}"
        for node_key, title, summary in active_topics
    )

    content_snippet = content_text[:1500] if content_text else "(không có nội dung)"

    prompt = (
        "Bạn là trợ lý phân loại tài liệu giáo vụ đại học.\n\n"
        f'Tài liệu: "{display_name}"\n'
        f"Nội dung (mục lục hoặc câu hỏi/trả lời):\n{content_snippet}\n\n"
        "Chủ đề hiện có:\n"
        f"{catalog_lines}\n\n"
        "Nhiệm vụ:\n"
        "1. Chọn các chủ đề PHÙ HỢP từ danh sách trên (0 đến 5 chủ đề).\n"
        "2. Nếu nội dung thuộc chủ đề HOÀN TOÀN MỚI không có trong danh sách, đề xuất thêm (tối đa 2).\n\n"
        "Trả về JSON:\n"
        '{"selected": ["topic:key1"], "new_topics": [{"slug": "ten-slug-viet-khong-dau", "title": "Tên", "summary": "Mô tả ngắn"}]}'
    )

    raw = await call_llm(prompt)

    try:
        data = json.loads(raw)
    except Exception:
        logger.warning(f"[TopicAssigner] JSON parse error: {raw[:200]}")
        return [], []

    selected = [k for k in (data.get("selected") or []) if k in valid_keys]
    new_topics = [
        t for t in (data.get("new_topics") or [])
        if isinstance(t, dict) and t.get("slug") and t.get("title")
    ]

    logger.info(
        f"[TopicAssigner] '{display_name}': selected={selected} new={[t['slug'] for t in new_topics]}"
    )
    return selected, new_topics
