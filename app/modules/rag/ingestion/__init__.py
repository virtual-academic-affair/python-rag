from app.modules.rag.ingestion.document_parser import DocumentParser, get_document_parser
from app.modules.rag.ingestion.corpus_linker import CorpusLinker, get_corpus_linker

__all__ = [
    "DocumentParser",
    "get_document_parser",
    "CorpusLinker",
    "get_corpus_linker",
    "FileIngestionResult",
    "IngestionService",
    "get_ingestion_service",
]


def __getattr__(name):
    if name in {"FileIngestionResult", "IngestionService", "get_ingestion_service"}:
        from app.modules.rag.ingestion.ingestion_service import (
            FileIngestionResult,
            IngestionService,
            get_ingestion_service,
        )

        exports = {
            "FileIngestionResult": FileIngestionResult,
            "IngestionService": IngestionService,
            "get_ingestion_service": get_ingestion_service,
        }
        return exports[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
