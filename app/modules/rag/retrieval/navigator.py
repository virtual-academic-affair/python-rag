"""Vectorless document navigator — the "PageIndex filesystem" candidate-finding layer.

Replaces Qdrant semantic chunk search + DocScore with a single LLM pass over a compact
catalog of document descriptions (relevance classification, not vector similarity).

The pure functions here (``render_catalog``, ``parse_navigation_response``) import only
the standard library so they stay trivially testable. The async orchestration class
``DocumentNavigator`` takes its LLM call as a dependency so it can be tested without a
network round-trip.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine, List, Optional


@dataclass
class CatalogEntry:
    """One row in the document catalog presented to the navigator LLM."""

    file_id: str
    file_name: str
    type: Optional[str] = None
    enrollment_year: Optional[dict] = None
    academic_year: Optional[dict] = None
    doc_description: str = ""
    headings: List[str] = field(default_factory=list)


def _fmt_year_range(yr: Optional[dict]) -> str:
    if not yr:
        return "mọi khóa"
    f, t = yr.get("from_year"), yr.get("to_year")
    if f in (None, 0) and t in (None, 9999):
        return "mọi khóa"
    if f == t:
        return str(f)
    return f"{f}-{t}"


def render_catalog(entries: List[CatalogEntry], max_headings: int = 15) -> str:
    """Render the catalog into the text block fed to the navigator LLM."""
    lines = []
    for i, c in enumerate(entries, 1):
        headings = c.headings[:max_headings]
        headings_str = " | ".join(headings) if headings else "(không có mục lục)"
        desc = (c.doc_description or "").strip() or "(không có mô tả)"
        lines.append(
            f"[{i}] {c.file_name}\n"
            f"    Loại: {c.type} | Khóa: {_fmt_year_range(c.enrollment_year)} "
            f"| Năm học: {_fmt_year_range(c.academic_year)}\n"
            f"    Mô tả: {desc}\n"
            f"    Mục lục: {headings_str}"
        )
    return "\n\n".join(lines)


def _loads_tolerant(raw_text: str) -> Any:
    """Parse JSON, tolerating markdown code fences the LLM may wrap it in."""
    text = (raw_text or "").strip()
    if text.startswith("```"):
        # drop the opening fence (``` or ```json) and the closing fence
        text = text.split("\n", 1)[-1] if "\n" in text else ""
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return None


def parse_navigation_response(raw_text: str, num_entries: int) -> List[dict]:
    """Parse the navigator LLM JSON into validated selections.

    Keeps only selections whose ``index`` is an int in ``[1, num_entries]``,
    de-duplicates by index (first wins), and preserves the LLM's ranking order.
    Returns ``[]`` for malformed output.
    """
    data = _loads_tolerant(raw_text)
    if not isinstance(data, dict):
        return []

    selections = data.get("selections")
    if not isinstance(selections, list):
        return []

    out: List[dict] = []
    seen: set[int] = set()
    for sel in selections:
        if not isinstance(sel, dict):
            continue
        idx = sel.get("index")
        if not isinstance(idx, int) or isinstance(idx, bool):
            continue
        if not (1 <= idx <= num_entries) or idx in seen:
            continue
        seen.add(idx)
        out.append({
            "index": idx,
            "score": sel.get("score"),
            "reason": sel.get("reason") or "",
        })
    return out


NAV_SYSTEM_PROMPT = """Bạn là bộ định tuyến tài liệu của hệ thống tư vấn Phòng Giáo vụ.

Cho một CÂU HỎI của sinh viên và một DANH MỤC tài liệu (mỗi tài liệu có số thứ tự, tên,
loại, khóa/năm học áp dụng, mô tả và mục lục), hãy chọn ra những tài liệu THỰC SỰ LIÊN QUAN
để trả lời câu hỏi.

Nguyên tắc:
- Đây là phân loại MỨC ĐỘ LIÊN QUAN, không phải so khớp từ khóa. Một tài liệu liên quan
  ngay cả khi không trùng từ ngữ, miễn nội dung của nó có thể trả lời câu hỏi.
- Ưu tiên đúng LOẠI văn bản và đúng KHÓA/NĂM HỌC nếu câu hỏi có nhắc tới.
- Nếu KHÔNG có tài liệu nào liên quan, trả về danh sách rỗng. Đừng chọn bừa.
- Chọn tối đa {top_k} tài liệu, xếp theo độ liên quan giảm dần.

CHỈ trả về JSON đúng schema:
{{
  "selections": [
    {{"index": <số thứ tự tài liệu>, "score": <0.0-1.0>, "reason": "<lý do ngắn gọn tiếng Việt>"}}
  ]
}}
"""

# An async callable that takes a fully-built prompt and returns the raw LLM text.
LLMCall = Callable[[str], Coroutine[Any, Any, str]]


class DocumentNavigator:
    """Picks relevant documents for a query via a single LLM pass over the catalog.

    The LLM call is injected so the orchestration can be tested without a network
    round-trip.
    """

    def __init__(self, llm_navigate: LLMCall):
        self._llm = llm_navigate

    def build_prompt(self, query: str, entries: List[CatalogEntry], top_k: int) -> str:
        catalog_text = render_catalog(entries)
        return (
            NAV_SYSTEM_PROMPT.format(top_k=top_k)
            + f'\n\nCÂU HỎI: "{query}"\n\nDANH MỤC TÀI LIỆU:\n{catalog_text}\n\nTrả về JSON:'
        )

    async def navigate(
        self, query: str, entries: List[CatalogEntry], top_k: int = 5
    ) -> List[dict]:
        """Return ranked ``[{entry, score, reason}]`` for the relevant documents."""
        if not entries:
            return []

        prompt = self.build_prompt(query, entries, top_k)
        raw = await self._llm(prompt)
        selections = parse_navigation_response(raw, len(entries))[:top_k]

        return [
            {
                "entry": entries[sel["index"] - 1],
                "score": sel["score"],
                "reason": sel["reason"],
            }
            for sel in selections
        ]


def build_candidate_files(nav_results: List[dict], doc_data_by_id: dict) -> List[dict]:
    """Map navigator results to the ``candidate_files`` contract used by the agent loop.

    ``doc_data_by_id`` maps ``file_id`` to a dict with ``storage_path``,
    ``markdown_storage_path``, ``table_of_contents``, ``doc_description`` and
    (already-serialized) ``structure``. Documents missing their original file or
    markdown artifact are treated as stale and dropped.
    """
    out: List[dict] = []
    for r in nav_results:
        entry = r["entry"]
        fid = entry.file_id
        data = doc_data_by_id.get(fid)
        if not data:
            continue
        if not data.get("storage_path") or not data.get("markdown_storage_path"):
            continue
        out.append({
            "file_id": fid,
            "file_name": entry.file_name,
            "doc_score": r["score"],
            "nav_reason": r["reason"],
            "doc_description": data.get("doc_description", "") or "",
            "structure": data.get("structure", []) or [],
            "markdown_storage_path": data.get("markdown_storage_path", ""),
            "storage_path": data.get("storage_path", ""),
            "table_of_contents": data.get("table_of_contents", []) or [],
        })
    return out
