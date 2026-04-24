"""
Text utilities for search normalization.
Supports accent-insensitive (unaccented) Vietnamese search.
"""
import unicodedata


def remove_accents(text: str) -> str:
    """
    Convert Vietnamese text to unaccented lowercase ASCII.

    Uses Unicode NFD decomposition to separate base characters from
    combining diacritics, then filters out the Mn (Mark, Nonspacing)
    category characters. Also maps đ/Đ to d explicitly since it does
    not decompose via NFD.

    Examples:
        "được" -> "duoc"
        "Điều kiện" -> "dieu kien"
        "dieu kien" -> "dieu kien"  (no-op on already plain text)
    """
    if not text:
        return ""
    # Preprocess: map đ/Đ which NFD won't decompose
    text = text.replace("đ", "d").replace("Đ", "d")
    # NFD decomposes composites: ê + ̣ (dot below) → two code points
    nfd = unicodedata.normalize("NFD", text.lower())
    # Drop all combining diacritic code points
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn")
