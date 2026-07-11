from unittest.mock import AsyncMock, patch

import pytest

from app.modules.corpus.dtos.traversal import Candidate
from app.modules.rag.query.retrieval.hydration.faq_hydrator import fetch_supporting_faqs


@pytest.mark.asyncio
async def test_fetch_supporting_faqs_is_best_effort_on_service_failure():
    with patch(
        "app.modules.faq.services.faq_service.get_faq_service",
        AsyncMock(side_effect=RuntimeError("faq down")),
    ):
        result = await fetch_supporting_faqs([Candidate("faq", "faq-1")])

    assert result == []
