from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from app.core.config import settings
from app.integrations.llm.gateway import LLMGateway, get_llm_gateway
from app.modules.faq.repositories.faq_repository import FaqRepository
from app.modules.rag.query.answering.faq_answering.contracts import FaqAnswerEntry, FaqAnswerResult
from app.modules.rag.query.answering.faq_answering.parser import parse_faq_answer_response
from app.modules.rag.query.answering.faq_answering.prompts import (
    CHAT_FAQ_ANSWER_SYSTEM_PROMPT,
    build_faq_answer_prompt,
)

logger = logging.getLogger(__name__)


class FaqAnswerService:
    """Generate a direct answer from retrieved FAQ context when it fully covers the query."""

    def __init__(self, llm_gateway: LLMGateway | None = None):
        self._faq_repo = FaqRepository()
        self._llm_gateway = llm_gateway or get_llm_gateway()

    async def _llm_answer(
        self,
        prompt: str,
        system_prompt: str,
    ) -> tuple[str, dict[str, int] | None]:
        resp = await self._llm_gateway.complete(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            model=settings.LLM_MODEL,
            temperature=settings.LLM_DETERMINISTIC_TEMPERATURE,
            response_format={"type": "json_object"},
        )
        return resp.text or "{}", resp.usage.as_dict() if resp.usage else None

    async def answer(
        self,
        question: str,
        faq_docs: list[Any],
        *,
        increment_view_count: bool = True,
        system_prompt: str = CHAT_FAQ_ANSWER_SYSTEM_PROMPT,
    ) -> Optional[FaqAnswerResult]:
        if not faq_docs:
            return None

        entries = self._build_entries(faq_docs)
        prompt = build_faq_answer_prompt(question, entries)
        raw_response, token_usage = await self._llm_answer(prompt, system_prompt)
        parsed = parse_faq_answer_response(raw_response, {entry.faq_id for entry in entries})
        if not parsed:
            logger.info("[FAQ-Answer] FAQ context did not fully answer: '%s'", question[:80])
            return None

        faq_by_id = {str(getattr(faq, "id", "")): faq for faq in faq_docs}
        matched_faqs: list[Any] = []
        for faq_id in parsed["faq_ids"]:
            matched_faq = faq_by_id.get(faq_id)
            if not matched_faq or getattr(matched_faq, "deleted_at", None) is not None:
                return None
            matched_faqs.append(matched_faq)

        logger.info("[FAQ-Answer] LLM answered from FAQ ids=%s", parsed["faq_ids"])
        if increment_view_count:
            for faq_id in parsed["faq_ids"]:
                asyncio.create_task(self._faq_repo.increment_view_count(faq_id))

        return FaqAnswerResult(
            answer_markdown=parsed["answer_markdown"],
            matched_faqs=matched_faqs,
            token_usage=token_usage,
        )

    @staticmethod
    def _build_entries(faq_docs: list[Any]) -> list[FaqAnswerEntry]:
        entries: list[FaqAnswerEntry] = []
        for faq in faq_docs:
            meta = getattr(faq, "metadata_filter", None)
            enrollment_year = meta.enrollment_year.model_dump() if meta and meta.enrollment_year else None
            academic_year = meta.academic_year.model_dump() if meta and meta.academic_year else None
            entries.append(FaqAnswerEntry(
                faq_id=str(getattr(faq, "id", "")),
                question=getattr(faq, "question", "") or "",
                answer_markdown=getattr(faq, "answer_markdown", "") or "",
                enrollment_year=enrollment_year,
                academic_year=academic_year,
            ))
        return entries


_faq_answer_service_instance: FaqAnswerService | None = None


def get_faq_answer_service() -> FaqAnswerService:
    global _faq_answer_service_instance
    if _faq_answer_service_instance is None:
        _faq_answer_service_instance = FaqAnswerService()
    return _faq_answer_service_instance
