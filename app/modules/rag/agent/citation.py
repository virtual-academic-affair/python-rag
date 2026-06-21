import logging
import re
import difflib
from app.integrations.storage.client import r2_storage

logger = logging.getLogger(__name__)

def verify_citations(
    text: str,
    sources_data: list[dict],
    resolve_citations: bool = False,
    citation_link_type: str = "original",  # "original" | "markdown"
) -> str:
    """Verify and optionally resolve citation markers."""
    valid_titles = [s["title"] for s in sources_data if s.get("title")]

    def _find_source_for_title(raw_title: str) -> dict | None:
        """Return the best-matching source dict for a given raw title."""
        for s in sources_data:
            vt = s.get("title", "")
            if raw_title.lower() in vt.lower() or vt.lower() in raw_title.lower():
                return s
        matches = difflib.get_close_matches(raw_title, [s.get("title", "") for s in sources_data], n=1, cutoff=0.6)
        if matches:
            for s in sources_data:
                if s.get("title") == matches[0]:
                    return s
        return None

    def verify_title(match):
        raw_title = match.group(1).strip()
        source = _find_source_for_title(raw_title)
        if not source:
            logger.warning(
                "[Citation] Citation removed: '%s' (no matching source found)",
                raw_title,
            )
            return ""

        verified_title = source.get("title", raw_title)
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

    if not text or not valid_titles:
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
            # Handle both numeric ref IDs and full hex IDs
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
                        pass

    def find_node_title(structure, page_or_line):
        nodes = []
        def traverse(n_list):
            for n in n_list:
                nodes.append(n)
                if n.get("nodes"):
                    traverse(n["nodes"])
        traverse(structure)
        valid_nodes = []
        for n in nodes:
            idx = n.get('line_num') or n.get('page_num')
            if idx is not None:
                valid_nodes.append((idx, n.get('title', '')))
        valid_nodes.sort(key=lambda x: x[0])
        closest_title = ""
        for idx, title in valid_nodes:
            if idx <= page_or_line:
                closest_title = title
            else:
                break
        return closest_title

    def extract_start_page(pages_str):
        try:
            parts = pages_str.split(',')
            first_part = parts[0].strip()
            if '-' in first_part:
                return int(first_part.split('-')[0].strip())
            return int(first_part)
        except (ValueError, AttributeError):
            return 0

    sources = []
    targets = accessed.items() if accessed else [] # Only show files actually read
    
    for i, (did, pages_list) in enumerate(targets):
        c = file_map[did]
        structure = c.get("structure", [])
        
        node_title = ""
        if pages_list and pages_list[0] is not None:
            first_pages = pages_list[0]
            start_idx = extract_start_page(first_pages)
            if start_idx > 0:
                node_title = find_node_title(structure, start_idx)
                
        orig_url = ""
        if c.get("storage_path"):
            orig_url = await r2_storage.get_file_url(c["storage_path"])
            
        md_url = ""
        if c.get("markdown_storage_path"):
            md_url = await r2_storage.get_file_url(c["markdown_storage_path"])
            
        sources.append({
            "citation_id": i + 1,
            "file_name": c.get("file_name", ""),
            "title": node_title,
            "file_id": did,
            "pages": pages_list if pages_list else None,
            "original_url": orig_url,
            "markdown_url": md_url
        })

    return sources
