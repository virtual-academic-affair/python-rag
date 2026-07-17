from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.modules.faq.models.faq import FaqDocument
    from app.modules.faq.repositories.faq_repository import FaqRepository
    from app.modules.faq.services.faq_service import FaqService


__all__ = [
    "get_faq_service",
    "FaqService",
    "FaqDocument",
    "FaqRepository",
]


def __getattr__(name: str) -> Any:
    if name in {"get_faq_service", "FaqService"}:
        from app.modules.faq.services.faq_service import FaqService, get_faq_service

        return {
            "get_faq_service": get_faq_service,
            "FaqService": FaqService,
        }[name]
    if name == "FaqDocument":
        from app.modules.faq.models.faq import FaqDocument

        return FaqDocument
    if name == "FaqRepository":
        from app.modules.faq.repositories.faq_repository import FaqRepository

        return FaqRepository
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
