"""Format conversion utilities: Markdown ↔ HTML Rich Text."""
import markdown as md_lib
import markdownify as mkfy

def markdown_to_rich_text(md: str) -> str:
    """Markdown → HTML Rich Text."""
    return md_lib.markdown(md or "", extensions=["tables", "fenced_code", "nl2br"])

def rich_text_to_markdown(html: str) -> str:
    """HTML Rich Text → Markdown (for AI use)."""
    return mkfy.markdownify(html or "", heading_style="ATX").strip()
