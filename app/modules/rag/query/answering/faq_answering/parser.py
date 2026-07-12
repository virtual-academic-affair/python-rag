from __future__ import annotations

import json
from typing import Any, Optional


def _loads_tolerant(raw_text: str) -> Any:
    text = (raw_text or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1] if "\n" in text else ""
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return None


def parse_faq_answer_response(raw_text: str, valid_faq_ids: set[str]) -> Optional[dict[str, Any]]:
    data = _loads_tolerant(raw_text)
    if not isinstance(data, dict):
        return None

    answer = data.get("answer")
    if answer is None:
        return None
    if not isinstance(answer, dict):
        return None

    faq_ids = answer.get("faq_ids")
    answer_markdown = answer.get("answer_markdown")
    if not isinstance(faq_ids, list) or not faq_ids:
        return None
    if not isinstance(answer_markdown, str) or not answer_markdown.strip():
        return None

    normalized_ids: list[str] = []
    seen_ids: set[str] = set()
    for faq_id in faq_ids:
        if not isinstance(faq_id, str):
            return None
        if faq_id not in valid_faq_ids:
            return None
        if faq_id in seen_ids:
            continue
        seen_ids.add(faq_id)
        normalized_ids.append(faq_id)

    return {
        "faq_ids": normalized_ids,
        "answer_markdown": answer_markdown.strip(),
    }
