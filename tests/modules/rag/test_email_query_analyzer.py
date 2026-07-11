from unittest.mock import AsyncMock, patch

import pytest

from app.modules.rag.query.analyzer.email_query_analyzer_service import (
    EmailQueryAnalyzer,
)


@pytest.mark.asyncio
async def test_email_inquiry_analyzer_normalizes_llm_result_without_regex():
    analyzer = EmailQueryAnalyzer.__new__(EmailQueryAnalyzer)
    analyzer._extract_structured_data = AsyncMock(return_value={
        "question": "Chuẩn ngoại ngữ K22?",
        "inquiry_types": ["graduation", "unknown"],
        "metadata_filter": {
            "enrollment_year": {"from_year": 2022, "to_year": 2022},
            "academic_year": None,
        },
    })

    with patch(
        "app.modules.rag.query.analyzer.email_query_analyzer_service.extract_metadata_from_text",
        AsyncMock(),
    ) as regex_mock:
        result = await analyzer.analyze_email("Tiêu đề", "Nội dung", sender_enrollment_year=2020)

    assert result.question == "Chuẩn ngoại ngữ K22?"
    assert result.inquiry_types == ["graduation"]
    assert result.metadata_filter == {"enrollment_year": {"from_year": 2022, "to_year": 2022}}
    regex_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_email_inquiry_analyzer_uses_regex_then_sender_cohort_fallback():
    analyzer = EmailQueryAnalyzer.__new__(EmailQueryAnalyzer)
    analyzer._extract_structured_data = AsyncMock(return_value={
        "question": "Hỏi lịch học",
        "inquiry_types": None,
        "metadata_filter": None,
    })

    with patch(
        "app.modules.rag.query.analyzer.email_query_analyzer_service.extract_metadata_from_text",
        AsyncMock(return_value={}),
    ) as regex_mock:
        result = await analyzer.analyze_email("Tiêu đề", "Nội dung", sender_enrollment_year=2023)

    assert result.question == "Hỏi lịch học"
    assert result.inquiry_types == ["training"]
    assert result.metadata_filter == {"enrollment_year": {"from_year": 2023, "to_year": 2023}}
    regex_mock.assert_awaited_once_with("Tiêu đề Nội dung")
