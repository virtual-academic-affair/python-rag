"""Lazy exports for query analyzers.

Keep this package import light: chat analyzer depends on chat DTOs, while email
workflow imports the email analyzer during app startup.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.modules.rag.query.analyzer.chat_query_analyzer_service import ChatQueryAnalyzer
    from app.modules.rag.query.analyzer.contracts import EmailQueryAnalysis
    from app.modules.rag.query.analyzer.email_query_analyzer_service import EmailQueryAnalyzer


__all__ = [
    "ChatQueryAnalyzer",
    "get_chat_query_analyzer",
    "EmailQueryAnalysis",
    "EmailQueryAnalyzer",
    "get_email_query_analyzer",
]


def __getattr__(name: str) -> Any:
    if name in {"ChatQueryAnalyzer", "get_chat_query_analyzer"}:
        from app.modules.rag.query.analyzer.chat_query_analyzer_service import (
            ChatQueryAnalyzer,
            get_chat_query_analyzer,
        )

        return {
            "ChatQueryAnalyzer": ChatQueryAnalyzer,
            "get_chat_query_analyzer": get_chat_query_analyzer,
        }[name]

    if name == "EmailQueryAnalysis":
        from app.modules.rag.query.analyzer.contracts import EmailQueryAnalysis

        return EmailQueryAnalysis

    if name in {"EmailQueryAnalyzer", "get_email_query_analyzer"}:
        from app.modules.rag.query.analyzer.email_query_analyzer_service import (
            EmailQueryAnalyzer,
            get_email_query_analyzer,
        )

        return {
            "EmailQueryAnalyzer": EmailQueryAnalyzer,
            "get_email_query_analyzer": get_email_query_analyzer,
        }[name]

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
