from __future__ import annotations
from enum import Enum
from pydantic import Field
from pymongo import IndexModel, ASCENDING
from app.core.base_document import BaseDocument

class NodeType(str, Enum):
    ROOT = "root"
    AXIS = "axis"
    METADATA = "metadata"
    TOPIC = "topic"
    FILE = "file"
    FAQ = "faq"

class NodeStatus(str, Enum):
    ACTIVE = "active"
    ARCHIVED = "archived"   # NO "pending" — topics created active immediately

class CorpusNodeDocument(BaseDocument):
    node_key: str = Field(..., description="Unique self-describing ID, e.g. 'topic:tot-nghiep'")
    node_type: NodeType
    title: str = ""
    summary: str = ""
    keywords: list[str] = Field(default_factory=list)
    metadata_filter: dict = Field(default_factory=dict)
    file_ids: list[str] = Field(default_factory=list)
    faq_ids: list[str] = Field(default_factory=list)
    child_keys: list[str] = Field(default_factory=list)
    parent_keys: list[str] = Field(default_factory=list)
    doc_count: int = 0
    faq_count: int = 0
    status: NodeStatus = NodeStatus.ACTIVE

    class Settings:
        name = "corpus_nodes"
        indexes = [
            IndexModel([("node_key", ASCENDING)], unique=True, name="idx_corpus_node_key"),
            "node_type",
            "status",
        ]
