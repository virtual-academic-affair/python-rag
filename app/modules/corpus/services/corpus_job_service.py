"""Corpus background job orchestration."""

from __future__ import annotations

import asyncio
import logging

from app.core.exceptions import ConflictException
from app.modules.corpus.dtos import BackfillStartResponse
from app.modules.corpus.services.corpus_service import CorpusService, get_corpus_service

logger = logging.getLogger(__name__)


class CorpusJobService:
    def __init__(self, corpus_service: CorpusService | None = None):
        self._corpus_service = corpus_service or get_corpus_service()
        self._backfill_running = False

    async def trigger_backfill(self) -> BackfillStartResponse:
        if self._backfill_running:
            raise ConflictException("A backfill task is already running.")

        self._backfill_running = True
        asyncio.create_task(self._run_backfill())
        return BackfillStartResponse(
            status="backfill_started",
            message="Check server logs for progress",
        )

    async def _run_backfill(self) -> None:
        try:
            await self._corpus_service.backfill_corpus()
        except Exception as exc:
            logger.error("[Corpus][Backfill] Fatal error: %s", exc, exc_info=True)
        finally:
            self._backfill_running = False


_corpus_job_service_instance: CorpusJobService | None = None


def get_corpus_job_service() -> CorpusJobService:
    global _corpus_job_service_instance
    if _corpus_job_service_instance is None:
        _corpus_job_service_instance = CorpusJobService()
    return _corpus_job_service_instance
