from __future__ import annotations
import json
import logging
from typing import Optional

from google.genai import types

from app.core.config import settings
from app.integrations.llm.gemini import gemini_client
from app.modules.rag.corpus.dtos.traversal import Candidate, TraversalResult
from app.modules.rag.corpus.repositories.corpus_node_repository import CorpusNodeRepository
from app.modules.rag.corpus.models.corpus_node import CorpusNodeDocument
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

    async def _decide_topics(
        self,
        question: str,
        topic_nodes: list[CorpusNodeDocument],
        descendant_titles: dict[str, list[str]] | None = None,
    ) -> list[tuple[str, str]]:
        """
        LLM quyết định cho TỪNG folder chủ đề: lấy hết hay mở con.
        Trả về [(node_key, action)] với action ∈ {"take", "open"}:
          - "take": folder chứa tài liệu phù hợp → lấy TOÀN BỘ file trong folder
                    và mọi folder con của nó, KHÔNG mở tiếp.
          - "open": có thể có tài liệu phù hợp nằm sâu hơn → mở các folder con
                    để xem xét chính xác hơn (không lấy file vội).
        Folder không liên quan thì không xuất hiện trong danh sách (bỏ qua).
        descendant_titles: tên con cháu có nội dung — chống mù routing ở tầng trên.
        """
        if not topic_nodes:
            return []

        def _line(n: CorpusNodeDocument) -> str:
            has_children = bool((descendant_titles or {}).get(n.node_key))
            line = f"- {n.node_key}: {n.title} — {n.summary}"
            kids = (descendant_titles or {}).get(n.node_key) or []
            if kids:
                line += f" (folder con: {', '.join(kids[:12])})"
            else:
                line += " (không có folder con)"
            return line

        catalog = "\n".join(_line(n) for n in topic_nodes)
        prompt = (
            "Bạn là trợ lý điều hướng kho tài liệu giáo vụ đại học, tổ chức dạng cây folder chủ đề.\n\n"
            f'Câu hỏi: "{question}"\n\n'
            f"Các folder ở tầng hiện tại:\n{catalog}\n\n"
            "Với TỪNG folder, quyết định một trong ba:\n"
            '- "take": folder này chứa tài liệu trả lời được câu hỏi → lấy TOÀN BỘ file '
            "trong folder và mọi folder con của nó, không cần xem chi tiết hơn.\n"
            '- "open": câu trả lời có thể nằm ở MỘT PHẦN folder con bên trong → mở ra '
            "xem danh sách folder con để chọn chính xác hơn (file sẽ không được lấy ở bước này).\n"
            "- BỎ QUA (không đưa vào danh sách): folder không liên quan đến câu hỏi.\n\n"
            "Lưu ý: folder không có folder con thì chỉ có thể \"take\" hoặc bỏ qua. "
            "Có thể bỏ qua tất cả nếu không folder nào phù hợp.\n\n"
            'Trả về JSON: {"decisions": [{"node": "key1", "action": "take"}, {"node": "key2", "action": "open"}]}'
        )
        try:
            raw = await self._call_llm(prompt)
        except Exception as e:
            logger.warning(f"[Corpus] _decide_topics LLM failed (best-effort): {e}")
            return []
        try:
            data = json.loads(raw)
            valid_keys = {n.node_key for n in topic_nodes}
            decisions = []
            for d in data.get("decisions") or []:
                if (
                    isinstance(d, dict)
                    and d.get("node") in valid_keys
                    and d.get("action") in ("take", "open")
                ):
                    decisions.append((d["node"], d["action"]))
            return decisions
        except Exception:
            logger.warning(f"[Corpus] _decide_topics parse error: {raw[:200]}")
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

        Mỗi vòng LLM quyết định cho từng folder ở tầng hiện tại:
          - "take": lấy toàn bộ candidates của folder + cả subtree, không mở tiếp
          - "open": mở folder con để xem xét tầng dưới (không lấy file của folder này)
          - bỏ qua: folder không liên quan
        Termination tự nhiên: LLM bỏ qua tất cả, hoặc không còn folder con mới để mở.
        Không có trần độ sâu cứng — tập `offered` đảm bảo mỗi node chỉ được đưa
        cho LLM đúng 1 lần, nên vòng lặp luôn kết thúc (kể cả khi data có vòng cha-con lỗi).
        """
        all_nodes = await self.repo.get_all()
        node_map = {n.node_key: n for n in all_nodes}

        # Filter trước khi travel: loại node mà cả subtree không chứa file/FAQ nào —
        # nhánh rỗng không đưa cho LLM chọn (đỡ nhiễu + đỡ token).
        def _subtree_has_content(key: str, seen: set[str]) -> bool:
            node = node_map.get(key)
            if not node:
                return False
            if node.file_ids or node.faq_ids:
                return True
            for ck in node.child_keys:
                if ck in seen:
                    continue
                seen.add(ck)
                if _subtree_has_content(ck, seen):
                    return True
            return False

        has_content = {
            n.node_key: _subtree_has_content(n.node_key, {n.node_key}) for n in all_nodes
        }

        # Tên các con cháu CÓ nội dung của từng node — để node sâu vẫn "hiện hình"
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
                if child and has_content.get(ck):
                    titles.append(child.title or ck)
                    titles.extend(_descendants(ck, seen))
            return titles

        descendant_titles = {
            n.node_key: _descendants(n.node_key, {n.node_key}) for n in all_nodes
        }

        frontier_nodes = [
            n for n in all_nodes if n.parent_key is None and has_content.get(n.node_key)
        ]
        logger.info(
            f"[Corpus] prefilter: {sum(has_content.values())}/{len(all_nodes)} topics có nội dung, "
            f"{len(frontier_nodes)} topic gốc vào traversal"
        )
        # Toàn bộ key trong subtree có nội dung (gồm chính node) — dùng khi "take"
        def _subtree_keys(key: str, seen: set[str]) -> list[str]:
            keys = [key]
            node = node_map.get(key)
            if not node:
                return keys
            for ck in node.child_keys:
                if ck in seen:
                    continue
                seen.add(ck)
                if node_map.get(ck) and has_content.get(ck):
                    keys.extend(_subtree_keys(ck, seen))
            return keys

        collected: list[str] = []
        offered: set[str] = {n.node_key for n in frontier_nodes}
        depth = 0

        while frontier_nodes:
            decisions = await self._decide_topics(question, frontier_nodes, descendant_titles)
            logger.info(f"[Corpus] traversal depth {depth}: decisions {decisions}")
            if not decisions:
                break  # termination: LLM bỏ qua tất cả folder ở tầng này

            frontier_map = {n.node_key: n for n in frontier_nodes}
            next_nodes: list[CorpusNodeDocument] = []
            for key, action in decisions:
                node = frontier_map.get(key)
                if not node:
                    continue
                # Folder không có con thì "open" cũng coi như "take"
                openable_children = [
                    ck for ck in node.child_keys
                    if node_map.get(ck) and has_content.get(ck)
                ]
                if action == "take" or not openable_children:
                    # Lấy toàn bộ candidates của folder + cả subtree, dừng nhánh này
                    collected.extend(_subtree_keys(key, {key}))
                else:
                    # Mở folder con — không lấy file của folder này
                    for ck in openable_children:
                        if ck not in offered:
                            offered.add(ck)
                            next_nodes.append(node_map[ck])
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
