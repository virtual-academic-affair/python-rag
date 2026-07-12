from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.modules.rag.query.answering.faq_answering.contracts import FaqAnswerEntry
from app.modules.rag.query.answering.faq_answering.parser import parse_faq_answer_response
from app.modules.rag.query.answering.faq_answering.prompts import build_faq_answer_prompt
from app.modules.rag.query.answering.faq_answering.service import FaqAnswerService


def test_faq_answer_prompt_rejects_partial_multi_intent_matches():
    prompt = build_faq_answer_prompt(
        "Chuẩn ngoại ngữ K22 và thủ tục xét tốt nghiệp là gì?",
        [
            FaqAnswerEntry(
                faq_id="faq1",
                question="Chuẩn ngoại ngữ K22 là gì?",
                answer_markdown="Sinh viên K22 cần đạt chuẩn B1.",
            )
        ],
    )

    assert "nhiều ý độc lập" in prompt
    assert "TOÀN BỘ câu hỏi" in prompt
    assert '{"answer": null}' in prompt


def test_parse_faq_answer_response_validates_ids_and_markdown():
    result = parse_faq_answer_response(
        '{"answer":{"faq_ids":["faq1","faq2"],"answer_markdown":"Câu trả lời tổng hợp"}}',
        {"faq1", "faq2"},
    )

    assert result == {
        "faq_ids": ["faq1", "faq2"],
        "answer_markdown": "Câu trả lời tổng hợp",
    }
    assert parse_faq_answer_response(
        '{"answer":{"faq_ids":["missing"],"answer_markdown":"Không hợp lệ"}}',
        {"faq1"},
    ) is None


async def test_faq_answer_service_reads_multiple_faqs_and_returns_llm_answer():
    service = FaqAnswerService()
    service._faq_repo = SimpleNamespace(increment_view_count=AsyncMock())
    service._llm_answer = AsyncMock(return_value=(
        '{"answer":{"faq_ids":["faq1","faq2"],"answer_markdown":"Bạn cần đạt chuẩn ngoại ngữ và nộp hồ sơ xét tốt nghiệp."}}',
        {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    ))
    faq_1 = SimpleNamespace(
        id="faq1",
        question="Chuẩn ngoại ngữ?",
        answer_markdown="Sinh viên cần đạt chuẩn ngoại ngữ theo khóa.",
        metadata_filter=None,
        is_active=True,
    )
    faq_2 = SimpleNamespace(
        id="faq2",
        question="Thủ tục xét tốt nghiệp?",
        answer_markdown="Sinh viên cần nộp hồ sơ xét tốt nghiệp đúng hạn.",
        metadata_filter=None,
        is_active=True,
    )

    result = await service.answer(
        "Chuẩn ngoại ngữ và thủ tục xét tốt nghiệp?",
        [faq_1, faq_2],
    )

    assert result.answer_markdown == "Bạn cần đạt chuẩn ngoại ngữ và nộp hồ sơ xét tốt nghiệp."
    assert [faq.id for faq in result.matched_faqs] == ["faq1", "faq2"]
    assert result.token_usage == {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
    assert service._faq_repo.increment_view_count.call_count == 2


async def test_faq_answer_service_can_skip_view_count_for_debug():
    service = FaqAnswerService()
    service._faq_repo = SimpleNamespace(increment_view_count=AsyncMock())
    service._llm_answer = AsyncMock(return_value=(
        '{"answer":{"faq_ids":["faq1"],"answer_markdown":"Câu trả lời debug"}}',
        None,
    ))
    faq = SimpleNamespace(
        id="faq1",
        question="Câu hỏi?",
        answer_markdown="Câu trả lời FAQ",
        metadata_filter=None,
        is_active=True,
    )

    result = await service.answer("Câu hỏi?", [faq], increment_view_count=False)

    assert result.answer_markdown == "Câu trả lời debug"
    service._faq_repo.increment_view_count.assert_not_called()
