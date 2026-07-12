from __future__ import annotations
from typing import Optional
from pydantic import Field
from pymongo import IndexModel, ASCENDING
from app.core.base_document import BaseDocument


class CorpusNodeDocument(BaseDocument):
    """
    Một node trong cây chủ đề (Corpus Tree). Mọi node đều là topic.
    File/FAQ không phải node — chúng là payload gắn trên topic.
    direct_* là payload gắn trực tiếp tại node này.
    subtree_* là aggregate của node này và toàn bộ node con.
    Topic gốc (tầng 1) có parent_key = None. Mỗi node có đúng 1 cha (cây thật).
    """
    node_key: str = Field(..., description="Unique slug ID, e.g. 'tot-nghiep'")
    title: str = ""
    summary: str = ""
    direct_file_ids: list[str] = Field(default_factory=list)
    direct_faq_ids: list[str] = Field(default_factory=list)
    subtree_file_ids: list[str] = Field(default_factory=list)
    subtree_faq_ids: list[str] = Field(default_factory=list)
    child_keys: list[str] = Field(default_factory=list)
    parent_key: Optional[str] = None
    file_count: int = 0
    faq_count: int = 0

    class Settings:
        name = "corpus_nodes"
        indexes = [
            IndexModel([("node_key", ASCENDING)], unique=True, name="idx_corpus_node_key"),
            "parent_key",
            "direct_file_ids",
            "direct_faq_ids",
            "subtree_file_ids",
            "subtree_faq_ids",
        ]
