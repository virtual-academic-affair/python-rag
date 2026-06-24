import logging
import re
import difflib
import asyncio
from app.integrations.storage.client import r2_storage

logger = logging.getLogger(__name__)

def _get_all_toc_titles(structure) -> list[str]:
    titles = []
    if not structure:
        return titles
    stack = list(structure)
    while stack:
        node = stack.pop()
        title = node.get("title")
        if title:
            titles.append(title)
        if node.get("nodes"):
            stack.extend(node["nodes"])
    return titles


def _flatten_structure(structure: list) -> list[tuple[int, str]]:
    """Flatten TOC structure into sorted list of (index, title) tuples. Called once per file."""
    nodes = []
    stack = list(structure)
    while stack:
        node = stack.pop()
        idx = node.get('line_num') or node.get('page_num')
        if idx is not None:
            title = node.get('title', '')
            nodes.append((idx, title))
        if node.get("nodes"):
            stack.extend(node["nodes"])
    nodes.sort(key=lambda x: x[0])
    return nodes


def _find_node_title_from_flat(flat_nodes: list[tuple[int, str]], page_or_line: int) -> str:
    """Binary-search style lookup on pre-sorted flat node list."""
    closest_title = ""
    for idx, title in flat_nodes:
        if idx <= page_or_line:
            closest_title = title
        else:
            break
    return closest_title


def verify_citations(
    text: str,
    sources_data: list[dict],
    resolve_citations: bool = False,
    citation_link_type: str = "original",  # "original" | "markdown"
) -> str:
    """Verify and optionally resolve citation markers."""

    # Pre-build lookup index once for all citations in this call
    _flat_titles: list[tuple[str, str]] = []  # (title_lower, original_title)
    _title_to_source: dict[str, dict] = {}
    _fname_to_source: dict[str, dict] = {}

    for s in sources_data:
        fname = (s.get("file_name") or "").strip()
        if fname:
            _fname_to_source[fname.lower()] = s

        t_val = s.get("titles") or s.get("title")
        titles = [t_val] if isinstance(t_val, str) else (t_val or [])
        for title in titles:
            if title:
                key = title.lower()
                if key not in _title_to_source:
                    _title_to_source[key] = s
                    _flat_titles.append((key, title))

        # Use pre-filtered table_of_contents if available (faster, blacklist-cleaned)
        # Otherwise fall back to full structure traversal
        toc_list = s.get("table_of_contents") or _get_all_toc_titles(s.get("structure", []))
        for t in toc_list:
            key = t.lower()
            if key not in _title_to_source:
                _title_to_source[key] = s
                _flat_titles.append((key, t))

    def _find_source_for_title(raw_title: str) -> tuple[dict, str] | None:
        """Return the best-matching (source_dict, matched_title) for a given raw title."""
        raw_clean = raw_title.strip().lower()
        if not raw_clean:
            return None

        # 1. Exact/substring match on titles
        for key, orig in _flat_titles:
            if raw_clean in key or key in raw_clean:
                return _title_to_source[key], orig

        # 2. Exact/substring match on file names
        for fname_lower, s in _fname_to_source.items():
            if raw_clean in fname_lower or fname_lower in raw_clean:
                return s, s.get("file_name", "")

        # 3. Fuzzy match across all collected titles + filenames
        all_options = [orig for _, orig in _flat_titles] + [s.get("file_name", "") for s in sources_data if s.get("file_name")]
        matches = difflib.get_close_matches(raw_title, all_options, n=1, cutoff=0.6)
        if matches:
            matched = matches[0]
            matched_lower = matched.lower()
            if matched_lower in _title_to_source:
                return _title_to_source[matched_lower], matched
            for s in sources_data:
                if s.get("file_name") == matched:
                    return s, matched

        return None

    def verify_title(match):
        raw_title = match.group(1).strip()
        result = _find_source_for_title(raw_title)
        if not result:
            logger.warning(
                "[Citation] Citation removed: '%s' (no matching source found)",
                raw_title,
            )
            return ""

        source, verified_title = result
        if raw_title != verified_title:
            logger.info(
                "[Citation] Citation normalized: '%s' -> '%s'",
                raw_title,
                verified_title,
            )

        if resolve_citations:
            if citation_link_type == "markdown":
                url = source.get("markdown_url", "")
            else:
                url = source.get("original_url", "")

            if url:
                return f"(Xem thêm tại [{verified_title}]({url}))"
            else:
                return f"(^{verified_title})"
        else:
            return f"(^{verified_title})"

    if not text or not sources_data:
        return re.sub(r'\(\^(.*?)\)', "", text) if text else text

    return re.sub(r'\(\^(.*?)\)', verify_title, text)


class CitationStreamFormatter:
    def __init__(
        self,
        sources_data: list[dict],
        resolve_citations: bool = False,
        citation_link_type: str = "markdown",
    ):
        self.sources_data = sources_data
        self.resolve_citations = resolve_citations
        self.citation_link_type = citation_link_type
        self.buffer = ""

    def process_chunk(self, chunk: str) -> str:
        self.buffer += chunk

        last_paren = self.buffer.rfind('(')
        if last_paren != -1:
            after_paren = self.buffer[last_paren:]
            if ')' not in after_paren:
                if after_paren.startswith('(^') or '(^'.startswith(after_paren):
                     ready_part = self.buffer[:last_paren]
                     pending_part = self.buffer[last_paren:]

                     processed = verify_citations(ready_part, self.sources_data, self.resolve_citations, self.citation_link_type)
                     self.buffer = pending_part
                     return processed

        processed = verify_citations(self.buffer, self.sources_data, self.resolve_citations, self.citation_link_type)
        self.buffer = ""
        return processed

    def flush(self) -> str:
        processed = verify_citations(self.buffer, self.sources_data, self.resolve_citations, self.citation_link_type)
        self.buffer = ""
        return processed


async def _resolve_source_urls(c: dict) -> tuple[str, str]:
    """Resolve original and markdown R2 URLs in parallel."""
    async def get_orig():
        if c.get("storage_path"):
            return await r2_storage.get_file_url(c["storage_path"])
        return ""

    async def get_md():
        if c.get("markdown_storage_path"):
            return await r2_storage.get_file_url(c["markdown_storage_path"])
        return ""

    return await asyncio.gather(get_orig(), get_md())


async def build_sources_from_steps(
    steps: list[dict],
    candidate_files: list[dict],
) -> list[dict]:
    """
    Build source citation list from actual agent tool calls.
    """
    file_map = {c["file_id"]: c for c in candidate_files}

    # file_id -> ordered unique list of access markers (pages or 'structure')
    accessed: dict[str, list[str]] = {}
    for step in steps:
        if step.get("type") == "call":
            name = step.get("name")
            args = step.get("args") or {}
            raw_fid = args.get("file_id")
            if raw_fid:
                raw_fid = str(raw_fid).strip().strip('[]')
                if raw_fid.isdigit():
                    idx = int(raw_fid) - 1
                    if 0 <= idx < len(candidate_files):
                        file_id = candidate_files[idx]["file_id"]
                    else:
                        file_id = raw_fid
                else:
                    file_id = raw_fid

                if file_id in file_map:
                    if file_id not in accessed:
                        accessed[file_id] = []

                    if name == "get_page_content":
                        pages = args.get("pages", "")
                        if pages and pages not in accessed[file_id]:
                            accessed[file_id].append(pages)
                    elif name == "get_document_structure":
                        if "structure" not in accessed[file_id]:
                            accessed[file_id].append("structure")

    def extract_start_page(pages_str):
        try:
            parts = pages_str.split(',')
            first_part = parts[0].strip()
            if '-' in first_part:
                return int(first_part.split('-')[0].strip())
            return int(first_part)
        except (ValueError, AttributeError):
            return 0

    targets = list(accessed.items())  # Only show files actually read

    async def build_one_source(i: int, did: str, pages_list: list[str]) -> dict:
        c = file_map[did]
        structure = c.get("structure", [])

        # Pre-flatten structure once per file (not once per page)
        flat_nodes = _flatten_structure(structure) if structure else []

        node_titles = []
        for pages in pages_list:
            if pages and pages != "structure":
                start_idx = extract_start_page(pages)
                if start_idx > 0:
                    t = _find_node_title_from_flat(flat_nodes, start_idx)
                    if t and t not in node_titles:
                        node_titles.append(t)

        if not node_titles:
            node_titles = [c.get("file_name", "")]

        orig_url, md_url = await _resolve_source_urls(c)

        pages_to_display = [p for p in pages_list if p != "structure"]
        return {
            "citation_id": i + 1,
            "file_name": c.get("file_name", ""),
            "titles": node_titles,
            "file_id": did,
            "pages": pages_to_display if pages_to_display else None,
            "original_url": orig_url,
            "markdown_url": md_url,
            "structure": structure,
        }

    sources = await asyncio.gather(
        *(build_one_source(i, did, pages_list) for i, (did, pages_list) in enumerate(targets))
    )
    return list(sources)
