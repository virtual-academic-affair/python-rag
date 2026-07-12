from __future__ import annotations

import asyncio

from app.modules.rag.query.retrieval.hydration import hydrate_source_files


def _flatten_structure(structure: list) -> list[tuple[int, str]]:
    """Flatten TOC structure into sorted list of (index, title) tuples."""
    nodes = []
    stack = list(structure)
    while stack:
        node = stack.pop()
        idx = node.get("line_num") or node.get("page_num")
        if idx is not None:
            title = node.get("title", "")
            nodes.append((idx, title))
        if node.get("nodes"):
            stack.extend(node["nodes"])
    nodes.sort(key=lambda x: x[0])
    return nodes


def _find_node_title_from_flat(flat_nodes: list[tuple[int, str]], page_or_line: int) -> str:
    closest_title = ""
    for idx, title in flat_nodes:
        if idx <= page_or_line:
            closest_title = title
        else:
            break
    return closest_title


async def build_sources_from_steps(
    steps: list[dict],
    candidate_files: list[dict],
) -> list[dict]:
    """Build source citation list from actual PageIndex tool calls."""
    file_map = {c["file_id"]: c for c in candidate_files}

    accessed: dict[str, list[str]] = {}
    for step in steps:
        if step.get("type") != "call":
            continue

        name = step.get("name")
        args = step.get("args") or {}
        raw_fid = args.get("file_id")
        if not raw_fid:
            continue

        raw_fid = str(raw_fid).strip().strip("[]")
        if raw_fid.isdigit():
            idx = int(raw_fid) - 1
            file_id = candidate_files[idx]["file_id"] if 0 <= idx < len(candidate_files) else raw_fid
        else:
            file_id = raw_fid

        if file_id not in file_map:
            continue

        accessed.setdefault(file_id, [])
        if name == "get_page_content":
            pages = args.get("pages", "")
            if pages and pages not in accessed[file_id]:
                accessed[file_id].append(pages)
        elif name == "get_document_structure" and "structure" not in accessed[file_id]:
            accessed[file_id].append("structure")

    def extract_start_page(pages_str):
        try:
            parts = pages_str.split(",")
            first_part = parts[0].strip()
            if "-" in first_part:
                return int(first_part.split("-")[0].strip())
            return int(first_part)
        except (ValueError, AttributeError):
            return 0

    targets = list(accessed.items())
    source_map = await hydrate_source_files([did for did, _ in targets])

    async def build_one_source(i: int, did: str, pages_list: list[str]) -> dict:
        candidate = file_map[did]
        source = source_map.get(did, candidate)
        structure = source.get("structure", [])
        flat_nodes = _flatten_structure(structure) if structure else []

        node_titles = []
        for pages in pages_list:
            if pages and pages != "structure":
                start_idx = extract_start_page(pages)
                if start_idx > 0:
                    title = _find_node_title_from_flat(flat_nodes, start_idx)
                    if title and title not in node_titles:
                        node_titles.append(title)

        if not node_titles:
            node_titles = [candidate.get("file_name", "")]

        pages_to_display = [p for p in pages_list if p != "structure"]
        return {
            "citation_id": i + 1,
            "file_name": candidate.get("file_name", ""),
            "titles": node_titles,
            "file_id": did,
            "pages": pages_to_display if pages_to_display else None,
            "original_url": source.get("original_url", ""),
            "markdown_url": source.get("markdown_url", ""),
            "structure": structure,
            "table_of_contents": source.get("table_of_contents", []),
        }

    sources = await asyncio.gather(
        *(build_one_source(i, did, pages_list) for i, (did, pages_list) in enumerate(targets))
    )
    return list(sources)
