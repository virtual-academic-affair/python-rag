from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.modules.rag.query.contracts import (
    QueryMode,
    RagQueryAnalysis,
    RagQueryBehavior,
    RagQueryInput,
    RagQueryResult,
)
from app.modules.rag.query.dtos import SourceCitation

if TYPE_CHECKING:
    from app.modules.rag.query.pipeline import RagQueryPipeline


__all__ = [
    "QueryMode",
    "RagQueryAnalysis",
    "RagQueryBehavior",
    "RagQueryInput",
    "RagQueryResult",
    "SourceCitation",
    "RagQueryPipeline",
    "get_rag_query_pipeline",
]


def __getattr__(name: str) -> Any:
    if name in {"RagQueryPipeline", "get_rag_query_pipeline"}:
        from app.modules.rag.query.pipeline import RagQueryPipeline, get_rag_query_pipeline

        return {
            "RagQueryPipeline": RagQueryPipeline,
            "get_rag_query_pipeline": get_rag_query_pipeline,
        }[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
