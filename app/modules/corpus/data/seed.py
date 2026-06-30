from __future__ import annotations
import logging
from app.modules.corpus.models.corpus_node import NodeType
from app.modules.corpus.repositories.corpus_node_repository import CorpusNodeRepository

logger = logging.getLogger(__name__)

ROOT_AND_AXES = [
    {"node_key": "root", "title": "Corpus", "summary": "Gốc kho dữ liệu", "parent": None},
    {"node_key": "axis:documents", "title": "Tài liệu", "summary": "Trục tài liệu", "parent": "root"},
    {"node_key": "axis:faqs", "title": "FAQ", "summary": "Trục FAQ", "parent": "root"},
    {"node_key": "axis:topics", "title": "Chủ đề", "summary": "Trục chủ đề", "parent": "root"},
    {"node_key": "axis:document_types", "title": "Loại văn bản", "summary": "Trục loại văn bản", "parent": "root"},
    {"node_key": "axis:enrollment_years", "title": "Khóa tuyển sinh", "summary": "Trục khóa", "parent": "root"},
    {"node_key": "axis:academic_years", "title": "Năm học", "summary": "Trục năm học", "parent": "root"},
]


async def seed_corpus(repo: CorpusNodeRepository) -> int:
    created = 0
    for n in ROOT_AND_AXES:
        if await repo.get_by_key(n["node_key"]):
            continue
        ntype = NodeType.ROOT if n["node_key"] == "root" else NodeType.AXIS
        await repo.upsert_node(
            n["node_key"],
            node_type=ntype,
            title=n["title"],
            summary=n["summary"],
            axis_parent_key=n["parent"],
        )
        created += 1
    logger.info(f"[Corpus] seed_corpus: tạo {created} node root/axis")
    return created
