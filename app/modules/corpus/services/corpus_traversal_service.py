from __future__ import annotations
import json
import logging
from typing import Optional

from google.genai import types

from app.core.config import settings
from app.integrations.llm.gemini import gemini_client
from app.modules.corpus.dtos.traversal import Candidate, TraversalResult
from app.modules.corpus.repositories.corpus_node_repository import CorpusNodeRepository
from app.modules.corpus.models.corpus_node import CorpusNodeDocument
from app.utils.retry import async_retry

logger = logging.getLogger(__name__)


class CorpusTraversalService:
    def __init__(self):
        self._repo: Optional[CorpusNodeRepository] = None

    @property
    def repo(self) -> CorpusNodeRepository:
        if self._repo is None:
            self._repo = CorpusNodeRepository()
        return self._repo

    async def _call_llm(self, prompt: str) -> str:
        model = settings.CORPUS_TOPIC_MODEL or settings.GEMINI_MODEL
        resp = await async_retry(
            gemini_client.client.aio.models.generate_content,
            model=model,
            contents=[prompt],
            config=types.GenerateContentConfig(
                temperature=0.0,
                response_mime_type="application/json",
            ),
        )
        return resp.text or "{}"

    async def _select_topics(
        self,
        question: str,
        topic_nodes: list[CorpusNodeDocument],
        descendant_titles: dict[str, list[str]] | None = None,
    ) -> list[str]:
        """
        LLM picks relevant topics from catalog. Returns list of valid node_keys.
        descendant_titles: tên các topic con cháu của mỗi node — đính kèm vào catalog
        để node sâu trong cây không bị "vô hình" khi LLM chọn ở tầng trên.
        """
        if not topic_nodes:
            return []

        def _line(n: CorpusNodeDocument) -> str:
            line = f"- {n.node_key}: {n.title} — {n.summary}"
            kids = (descendant_titles or {}).get(n.node_key) or []
            if kids:
                line += f" (bao gồm: {', '.join(kids[:12])})"
            return line

        catalog = "\n".join(_line(n) for n in topic_nodes)
        prompt = (
            "Bạn là trợ lý phân loại câu hỏi giáo vụ đại học.\n\n"
            f'Câu hỏi: "{question}"\n\n'
            f"Các chủ đề tài liệu:\n{catalog}\n\n"
            "Chọn các chủ đề PHÙ HỢP với câu hỏi (0 đến 5 chủ đề, có thể không chọn nào).\n"
            'Trả về JSON: {"selected_topics": ["topic:key1", "topic:key2"]}'
        )
        try:
            raw = await self._call_llm(prompt)
        except Exception as e:
            logger.warning(f"[Corpus] _select_topics LLM failed (best-effort): {e}")
            return []
        try:
            data = json.loads(raw)
            valid_keys = {n.node_key for n in topic_nodes}
            return [k for k in (data.get("selected_topics") or []) if k in valid_keys]
        except Exception:
            logger.warning(f"[Corpus] _select_topics parse error: {raw[:200]}")
            return []

    async def expand_nodes(self, node_keys: list[str]) -> dict[str, list[CorpusNodeDocument]]:
        """Expand each node_key to its direct children."""
        result = {}
        for key in node_keys:
            children = await self.repo.get_children(key)
            result[key] = children
        return result

    async def _traverse_topics(self, question: str) -> list[str]:
        """
        Corpus Traversal: duyệt lặp cây topic từ các topic gốc, sâu theo cây thực tế.

        Mỗi vòng: LLM chọn node liên quan trong tầng hiện tại →
        drill-down vào các node được chọn còn có topic con.
        Termination tự nhiên: LLM không chọn node nào, hoặc không còn node con mới.
        Không có trần độ sâu cứng — tập `offered` đảm bảo mỗi node chỉ được đưa
        cho LLM đúng 1 lần, nên vòng lặp luôn kết thúc (kể cả khi data có vòng cha-con lỗi).
        Node được chọn ở mọi tầng đều được gộp vào kết quả (gộp candidate cha + con).
        """
        all_nodes = await self.repo.get_all()
        node_map = {n.node_key: n for n in all_nodes}

        # Tên toàn bộ con cháu của từng node — để node sâu vẫn "hiện hình"
        # trong catalog khi LLM chọn ở các tầng trên (chống mù routing).
        def _descendants(key: str, seen: set[str]) -> list[str]:
            titles: list[str] = []
            node = node_map.get(key)
            if not node:
                return titles
            for ck in node.child_keys:
                if ck in seen:
                    continue
                seen.add(ck)
                child = node_map.get(ck)
                if child:
                    titles.append(child.title or ck)
                    titles.extend(_descendants(ck, seen))
            return titles

        descendant_titles = {
            n.node_key: _descendants(n.node_key, {n.node_key}) for n in all_nodes
        }

        frontier_nodes = [n for n in all_nodes if not n.parent_keys]
        collected: list[str] = []
        offered: set[str] = {n.node_key for n in frontier_nodes}
        depth = 0

        while frontier_nodes:
            selected_keys = await self._select_topics(question, frontier_nodes, descendant_titles)
            logger.info(f"[Corpus] traversal depth {depth}: selected {selected_keys}")
            if not selected_keys:
                break  # termination: không có nhánh phù hợp

            collected.extend(selected_keys)

            # Drill-down: chỉ đi tiếp vào node được chọn còn có con chưa duyệt
            selected_nodes = [n for n in frontier_nodes if n.node_key in selected_keys]
            next_nodes: list[CorpusNodeDocument] = []
            for n in selected_nodes:
                for ck in n.child_keys:
                    child = node_map.get(ck)
                    if child and child.node_key not in offered:
                        offered.add(child.node_key)
                        next_nodes.append(child)
            frontier_nodes = next_nodes
            depth += 1

        return list(dict.fromkeys(collected))

    async def resolve_candidates(self, selected_keys: list[str]) -> TraversalResult:
        """Gộp file_ids/faq_ids từ các topic được chọn (dedupe, giữ thứ tự chọn)."""
        nodes = await self.repo.get_by_keys(selected_keys)
        # Giữ thứ tự theo selected_keys để kết quả ổn định giữa các lần gọi
        node_map = {n.node_key: n for n in nodes}

        seen_files: set[str] = set()
        seen_faqs: set[str] = set()
        file_candidates: list[Candidate] = []
        supporting_faqs: list[Candidate] = []

        for key in selected_keys:
            node = node_map.get(key)
            if not node:
                continue
            for file_id in node.file_ids:
                if file_id not in seen_files:
                    seen_files.add(file_id)
                    file_candidates.append(Candidate("file", file_id))
            for faq_id in node.faq_ids:
                if faq_id not in seen_faqs:
                    seen_faqs.add(faq_id)
                    supporting_faqs.append(Candidate("faq", faq_id))

        logger.info(
            f"[Corpus] resolve_candidates: {len(file_candidates)} files, "
            f"{len(supporting_faqs)} faqs (topics={selected_keys})"
        )
        return TraversalResult(file_candidates=file_candidates, supporting_faqs=supporting_faqs)

    async def traverse(self, question: str) -> TraversalResult:
        """
        Corpus Traversal: duyệt cây topic bằng LLM (drill-down từ topic gốc),
        gộp toàn bộ file/faq thuộc các topic được chọn.
        Lọc metadata (khóa/năm học/quyền) thực hiện ở bước enrich phía sau.
        """
        logger.info(f"[Corpus] traverse start: '{question[:80]}'")

        selected_topic_keys = await self._traverse_topics(question)
        logger.info(f"[Corpus] topic selection: {selected_topic_keys}")

        if not selected_topic_keys:
            return TraversalResult()

        return await self.resolve_candidates(selected_topic_keys)


_instance: Optional[CorpusTraversalService] = None


def get_corpus_traversal_service() -> CorpusTraversalService:
    global _instance
    if _instance is None:
        _instance = CorpusTraversalService()
    return _instance
