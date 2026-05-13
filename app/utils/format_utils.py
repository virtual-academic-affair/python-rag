"""Format conversion utilities: Markdown ↔ HTML Rich Text."""
import re
import markdown as md_lib
import markdownify as mkfy
from pylatexenc.latex2text import LatexNodes2Text

# Singleton converter for performance
_latex_converter = LatexNodes2Text(math_mode="text")

def sanitize_latex_in_markdown(text: str) -> str:
    """
    Chuyển đổi các block inline LaTeX ($...$) sang Unicode/text thuần
    sử dụng thư viện pylatexenc.

    Ví dụ:
      $\\rightarrow$  → →
      $\\approx$      → ≈
      $\\frac{a}{b}$  → a/b  (pylatexenc render text thuần)

    Các block không parse được sẽ được giữ nguyên.
    """
    if not text:
        return text

    def _replace(m: re.Match) -> str:
        inner = m.group(1).strip()
        try:
            result = _latex_converter.latex_to_text(inner).strip()
            # Nếu kết quả rỗng (không parse được gì có nghĩa) thì giữ nguyên gốc
            return result if result else m.group(0)
        except Exception:
            # Fallback giữ nguyên block $...$ nếu có lỗi parse
            return m.group(0)

    # Replace delimited inline math blocks: $cmd$
    return re.sub(r"\$([^$\n]+?)\$", _replace, text)


def markdown_to_rich_text(md: str) -> str:
    """Markdown → HTML Rich Text.

    Automatically sanitizes inline LaTeX commands (e.g. ``$\\le$``,
    ``$\\geq$``) to Unicode equivalents before converting, so the resulting
    HTML is safe for email clients and rich-text renderers.
    """
    clean = sanitize_latex_in_markdown(md or "")
    return md_lib.markdown(clean, extensions=["tables", "fenced_code", "nl2br"])


def rich_text_to_markdown(html: str) -> str:
    """HTML Rich Text → Markdown (for AI use)."""
    return mkfy.markdownify(html or "", heading_style="ATX").strip()
