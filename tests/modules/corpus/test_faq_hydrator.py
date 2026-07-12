from unittest.mock import AsyncMock, patch

import pytest

from app.modules.corpus.contracts import FaqCandidate
from app.modules.rag.query.retrieval.hydration.faq_hydrator import hydrate_faq_candidate_docs


@pytest.mark.asyncio
async def test_hydrate_faq_candidate_docs_is_best_effort_on_service_failure():
    with patch(
        "app.modules.faq.services.faq_service.get_faq_service",
        AsyncMock(side_effect=RuntimeError("faq down")),
    ):
        result = await hydrate_faq_candidate_docs([FaqCandidate("faq-1")])

    assert result == []
