import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.integrations.llm.contracts import LLMResponse
from app.modules.faq.services.faq_synthesizer_service import FaqSynthesisService


@pytest.mark.asyncio
async def test_faq_synthesis_uses_system_and_user_messages():
    text = json.dumps({
        "question": "Điều kiện tốt nghiệp là gì?",
        "answer_draft": "Sinh viên cần hoàn thành chương trình đào tạo.",
        "metadata_filter_suggestion": None,
    }, ensure_ascii=False)
    gateway = SimpleNamespace(complete=AsyncMock(return_value=LLMResponse(
        text=text,
        tool_calls=[],
        assistant_message={"role": "assistant", "content": text},
    )))
    service = FaqSynthesisService(llm_gateway=gateway)
    cluster = [SimpleNamespace(
        id="507f1f77bcf86cd799439011",
        source_type="chat",
        question="Khi nào đủ điều kiện tốt nghiệp?",
        answer_markdown="Hoàn thành chương trình đào tạo.",
        metadata_filter=None,
    )]
    metadata_service = MagicMock()
    metadata_service.validate_and_parse_faq_metadata.return_value = (True, [], None)

    with patch(
        "app.modules.faq.services.faq_synthesizer_service.get_metadata_service",
        return_value=metadata_service,
    ), patch(
        "app.modules.faq.services.faq_synthesizer_service.FaqCandidateDocument",
        side_effect=lambda **values: SimpleNamespace(**values),
    ):
        candidate = await service._synthesize_cluster(cluster, "batch-1", [])

    assert candidate is not None
    assert candidate.question == "Điều kiện tốt nghiệp là gì?"
    messages = gateway.complete.await_args.kwargs["messages"]
    assert [message["role"] for message in messages] == ["system", "user"]
    assert '"question": "Synthesized Vietnamese question"' in messages[0]["content"]
    assert "Khi nào đủ điều kiện tốt nghiệp?" in messages[1]["content"]
    assert gateway.complete.await_args.kwargs["response_format"] == {"type": "json_object"}
