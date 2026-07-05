from __future__ import annotations
from pydantic import Field
from pymongo import IndexModel, ASCENDING
from app.core.base_document import BaseDocument


class CorpusNodeDocument(BaseDocument):
    """
    Một node trong cây chủ đề (Corpus Tree). Mọi node đều là topic.
    File/FAQ không phải node — chúng là payload (file_ids/faq_ids) gắn trên topic.
    Topic gốc (tầng 1) có parent_keys rỗng.
    """
    node_key: str = Field(..., description="Unique self-describing ID, e.g. 'topic:tot-nghiep'")
    title: str = ""
    summary: str = ""
    keywords: list[str] = Field(default_factory=list)
    file_ids: list[str] = Field(default_factory=list)
    faq_ids: list[str] = Field(default_factory=list)
    child_keys: list[str] = Field(default_factory=list)
    parent_keys: list[str] = Field(default_factory=list)
    doc_count: int = 0
    faq_count: int = 0

    class Settings:
        name = "corpus_nodes"
        indexes = [
            IndexModel([("node_key", ASCENDING)], unique=True, name="idx_corpus_node_key"),
            "parent_keys",
            "file_ids",
            "faq_ids",
        ]
