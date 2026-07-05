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
      new_topics:    genuinely new topics [{slug, title, summary, parent}]
                     — "parent" is a node_key from active_topics (the proposed
                     parent topic in the hierarchy) or None for a top-level topic.

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
        "Chủ đề hiện có (dạng cây, chủ đề con cụ thể hơn chủ đề cha):\n"
        f"{catalog_lines}\n\n"
        "Nhiệm vụ:\n"
        "1. Chọn các chủ đề PHÙ HỢP từ danh sách trên (0 đến 5 chủ đề). "
        "ƯU TIÊN chủ đề con CỤ THỂ NHẤT thay vì chủ đề cha chung chung.\n"
        "2. Nếu nội dung thuộc chủ đề HOÀN TOÀN MỚI không có trong danh sách, đề xuất thêm (tối đa 2). "
        'Với mỗi chủ đề mới, chọn "parent" là node_key của chủ đề cha phù hợp nhất trong danh sách trên '
        "(hoặc null nếu là nhóm chủ đề lớn hoàn toàn mới).\n\n"
        "Trả về JSON:\n"
        '{"selected": ["topic:key1"], "new_topics": [{"slug": "ten-slug-viet-khong-dau", "title": "Tên", "summary": "Mô tả ngắn", "parent": "topic:key-cha"}]}'
    )

    raw = await call_llm(prompt)

    try:
        data = json.loads(raw)
    except Exception:
        logger.warning(f"[TopicAssigner] JSON parse error: {raw[:200]}")
        return [], []

    selected = [k for k in (data.get("selected") or []) if k in valid_keys]
    new_topics = []
    for t in data.get("new_topics") or []:
        if not (isinstance(t, dict) and t.get("slug") and t.get("title")):
            continue
        # Parent phải là node_key có thật trong catalog, nếu không → top-level
        if t.get("parent") not in valid_keys:
            t["parent"] = None
        new_topics.append(t)

    logger.info(
        f"[TopicAssigner] '{display_name}': selected={selected} new={[t['slug'] for t in new_topics]}"
    )
    return selected, new_topics
