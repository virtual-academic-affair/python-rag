import difflib
import logging
import re

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


def verify_citations(
    text: str,
    sources_data: list[dict],
    resolve_citations: bool = False,
    citation_link_type: str = "original",
) -> str:
    """Verify and optionally resolve citation markers."""
    flat_titles: list[tuple[str, str]] = []
    title_to_source: dict[str, dict] = {}
    fname_to_source: dict[str, dict] = {}

    for source in sources_data:
        fname = (source.get("file_name") or "").strip()
        if fname:
            fname_to_source[fname.lower()] = source

        title_value = source.get("titles") or source.get("title")
        titles = [title_value] if isinstance(title_value, str) else (title_value or [])
        for title in titles:
            if title:
                key = title.lower()
                if key not in title_to_source:
                    title_to_source[key] = source
                    flat_titles.append((key, title))

        toc_list = source.get("table_of_contents") or _get_all_toc_titles(source.get("structure", []))
        for title in toc_list:
            key = title.lower()
            if key not in title_to_source:
                title_to_source[key] = source
                flat_titles.append((key, title))

    def _find_source_for_title(raw_title: str) -> tuple[dict, str] | None:
        raw_clean = raw_title.strip().lower()
        if not raw_clean:
            return None

        for key, original_title in flat_titles:
            if raw_clean in key or key in raw_clean:
                return title_to_source[key], original_title

        for fname_lower, source in fname_to_source.items():
            if raw_clean in fname_lower or fname_lower in raw_clean:
                return source, source.get("file_name", "")

        all_options = [
            original_title for _, original_title in flat_titles
        ] + [
            source.get("file_name", "") for source in sources_data if source.get("file_name")
        ]
        matches = difflib.get_close_matches(raw_title, all_options, n=1, cutoff=0.6)
        if matches:
            matched = matches[0]
            matched_lower = matched.lower()
            if matched_lower in title_to_source:
                return title_to_source[matched_lower], matched
            for source in sources_data:
                if source.get("file_name") == matched:
                    return source, matched

        return None

    def verify_title(match):
        raw_title = match.group(1).strip()
        result = _find_source_for_title(raw_title)
        if not result:
            logger.warning("[Citation] Citation removed: '%s' (no matching source found)", raw_title)
            return ""

        source, verified_title = result
        if raw_title != verified_title:
            logger.info("[Citation] Citation normalized: '%s' -> '%s'", raw_title, verified_title)

        if not resolve_citations:
            return f"(^{verified_title})"

        url = source.get("markdown_url", "") if citation_link_type == "markdown" else source.get("original_url", "")
        if url:
            return f"(Xem thêm tại [{verified_title}]({url}))"
        return f"(^{verified_title})"

    if not text or not sources_data:
        return re.sub(r"\(\^(.*?)\)", "", text) if text else text

    return re.sub(r"\(\^(.*?)\)", verify_title, text)
