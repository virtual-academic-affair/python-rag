from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.modules.faq.models.faq import FaqDocument
    from app.modules.faq.models.faq_candidate import FaqCandidateDocument
    from app.modules.faq.models.interaction_log import InteractionLogDocument
    from app.modules.faq.repositories.faq_candidate_repository import FaqCandidateRepository
    from app.modules.faq.repositories.faq_repository import FaqRepository
    from app.modules.faq.repositories.interaction_log_repository import InteractionLogRepository
    from app.modules.faq.services.faq_service import FaqService
    from app.modules.faq.services.faq_synthesizer_service import FaqSynthesisService


__all__ = [
    "get_faq_service",
    "FaqService",
    "get_faq_synthesis_service",
    "FaqSynthesisService",
    "FaqDocument",
    "FaqCandidateDocument",
    "InteractionLogDocument",
    "FaqRepository",
    "FaqCandidateRepository",
    "InteractionLogRepository",
]


def __getattr__(name: str) -> Any:
    if name in {"get_faq_service", "FaqService"}:
        from app.modules.faq.services.faq_service import FaqService, get_faq_service

        return {
            "get_faq_service": get_faq_service,
            "FaqService": FaqService,
        }[name]
    if name in {"get_faq_synthesis_service", "FaqSynthesisService"}:
        from app.modules.faq.services.faq_synthesizer_service import (
            FaqSynthesisService,
            get_faq_synthesis_service,
        )

        return {
            "get_faq_synthesis_service": get_faq_synthesis_service,
            "FaqSynthesisService": FaqSynthesisService,
        }[name]
    if name == "FaqDocument":
        from app.modules.faq.models.faq import FaqDocument

        return FaqDocument
    if name == "FaqCandidateDocument":
        from app.modules.faq.models.faq_candidate import FaqCandidateDocument

        return FaqCandidateDocument
    if name == "InteractionLogDocument":
        from app.modules.faq.models.interaction_log import InteractionLogDocument

        return InteractionLogDocument
    if name == "FaqRepository":
        from app.modules.faq.repositories.faq_repository import FaqRepository

        return FaqRepository
    if name == "FaqCandidateRepository":
        from app.modules.faq.repositories.faq_candidate_repository import FaqCandidateRepository

        return FaqCandidateRepository
    if name == "InteractionLogRepository":
        from app.modules.faq.repositories.interaction_log_repository import InteractionLogRepository

        return InteractionLogRepository
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
