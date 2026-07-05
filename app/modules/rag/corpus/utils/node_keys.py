from __future__ import annotations
import re
import unicodedata


def slugify_topic(title: str) -> str:
    s = unicodedata.normalize("NFD", title.strip().lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = s.replace("đ", "d")
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s
