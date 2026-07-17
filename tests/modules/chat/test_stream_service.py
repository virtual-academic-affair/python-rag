import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.modules.chat.dtos import ChatHistoryItem, UserContext
from app.modules.chat.repositories.chat_history_repository import PERSISTED_STEP_TYPES
from app.modules.chat.services.chat_service import ChatService
from app.modules.chat.services.chat_stream_service import ChatStreamService
from app.modules.rag.query import RagQueryInput


async def _collect(generator):
    rows = []
    async for item in generator:
        rows.append(json.loads(item))
    return rows


@pytest.mark.asyncio
async def test_chat_non_stream_returns_corpus_reasoning_without_persisting_it():
    svc = ChatService.__new__(ChatService)
    svc._rag_query = SimpleNamespace(answer_chat=AsyncMock(return_value=SimpleNamespace(
        answer_markdown="Không tìm thấy tài liệu.",
        candidate_files=[],
        token_usage=None,
        steps=[
            {"type": "reasoning", "content": "Cần kiểm tra nhánh tốt nghiệp."},
            {
                "type": "corpus_traversal",
                "action": "select",
                "node_keys": ["tot-nghiep", "ngoai-ngu"],
                "content": 'Chọn các chủ đề: "Tốt nghiệp", "Ngoại ngữ".',
            },
        ],
        is_direct_reply=False,
        source="bypass",
        max_turns_reached=False,
        sources=[],
        analysis=None,
    )))

    result = await svc.generate_chat_response(
        "Điều kiện tốt nghiệp?",
        UserContext(user_id="u1", name="User", role="student"),
        [],
    )

    assert result["steps"] == [
        {"type": "reasoning", "content": "Cần kiểm tra nhánh tốt nghiệp."},
        {
            "type": "corpus_traversal",
            "action": "select",
            "nodeKeys": ["tot-nghiep", "ngoai-ngu"],
            "content": 'Chọn các chủ đề: "Tốt nghiệp", "Ngoại ngữ".',
        },
    ]
    assert "corpus_tree" in PERSISTED_STEP_TYPES
    assert "reasoning" not in PERSISTED_STEP_TYPES


def test_faq_recommendation_uses_only_matched_faqs_and_accessed_files():
    analysis = SimpleNamespace(
        needs_rag=True,
        effective_question="Điều kiện tốt nghiệp khóa 2022?",
        metadata_filter={
            "enrollment_year": {"from_year": 2022, "to_year": 2022},
        },
    )
    restricted_matched_faq = SimpleNamespace(lecturer_only=True)
    candidate_files = [
        {"file_id": "used", "lecturer_only": False},
        {"file_id": "unused", "lecturer_only": True},
    ]

    recommendation = ChatService._build_faq_recommendation(
        analysis=analysis,
        sources=[{"file_id": "used"}],
        candidate_files=candidate_files,
        used_faq_docs=[],
    )

    assert recommendation.model_dump(by_alias=True) == {
        "effectiveQuestion": "Điều kiện tốt nghiệp khóa 2022?",
        "metadata": {
            "enrollmentYear": {"fromYear": 2022, "toYear": 2022},
            "academicYear": {"fromYear": 0, "toYear": 9999},
        },
        "lecturerOnly": False,
    }

    recommendation = ChatService._build_faq_recommendation(
        analysis=analysis,
        sources=[],
        candidate_files=candidate_files,
        used_faq_docs=[restricted_matched_faq],
    )
    assert recommendation.lecturer_only is True

    recommendation = ChatService._build_faq_recommendation(
        analysis=analysis,
        sources=[],
        candidate_files=candidate_files,
        used_faq_docs=[],
    )
    assert recommendation.lecturer_only is False


def test_faq_recommendation_is_none_for_direct_answer():
    recommendation = ChatService._build_faq_recommendation(
        analysis=SimpleNamespace(
            needs_rag=False,
            effective_question="Cảm ơn",
            metadata_filter={},
        ),
        sources=[],
        candidate_files=[],
        used_faq_docs=[],
    )

    assert recommendation is None


@pytest.mark.asyncio
async def test_chat_stream_service_formats_agent_events_and_final_payload():
    svc = ChatStreamService.__new__(ChatStreamService)

    class FakePipeline:
        requests = []

        async def stream_chat(self, request: RagQueryInput):
            self.requests.append(request)
            yield {
                "type": "_query_analysis_start",
                "content": "Phân tích câu hỏi của người dùng...",
            }
            yield {
                "type": "_query_analysis",
                "step": {
                    "type": "query_analysis",
                    "original_question": "câu hỏi gốc",
                    "effective_question": "câu hỏi tra cứu đã chuẩn hóa",
                    "needs_rag": True,
                    "metadata_filter": {
                        "enrollment_year": {"from_year": 2022, "to_year": 2022},
                    },
                },
            }
            yield {
                "type": "_corpus_tree",
                "content": "Tải cây chủ đề phù hợp.",
                "tree": [{
                    "nodeKey": "root",
                    "title": "Gốc",
                    "summary": "",
                    "children": [],
                }],
            }
            yield {
                "type": "_corpus_traversal",
                "step": {
                    "type": "corpus_traversal",
                    "action": "select",
                    "node_keys": ["root", "other"],
                    "content": 'Chọn các chủ đề: "Gốc", "Khác".',
                },
            }
            yield {"type": "_corpus_traversal_end", "traversal_complete": True}
            yield {
                "type": "_pipeline_step",
                "step": {
                    "type": "file_retrieval",
                    "candidate_files": [{"file_id": "file-1", "file_name": "Quy chế"}],
                },
                "candidate_files": [{
                    "file_id": "file-1",
                    "file_name": "Quy chế",
                    "doc_description": "Mô tả",
                    "lecturer_only": True,
                }],
                "faq_docs": [],
            }
            yield {"type": "call", "step": {"type": "call", "name": "get_document_structure", "args": {"file_id": "1"}}, "done": False}
            yield {"type": "text", "content": "Câu trả lời", "done": False}
            yield {
            "type": "_agent_result",
            "final_answer": "Câu trả lời",
            "max_turns_reached": False,
            "steps": [{"type": "call", "name": "get_document_structure", "args": {"file_id": "1"}}],
            "sources": [{
                "citation_id": 1,
                "file_id": "file-1",
                "file_name": "Quy chế",
            }],
                "token_usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
            }

    fake_pipeline = FakePipeline()
    svc._rag_query = fake_pipeline

    rows = await _collect(svc.stream_chat_response(
        "q",
        UserContext(user_id="u1", name="User", role="student"),
        [ChatHistoryItem(role="user", content="q")],
    ))

    assert any(row.get("content") == "Đang tra cứu cấu trúc mục lục của 'Quy chế'." for row in rows)
    tree = next(row for row in rows if row.get("type") == "corpus_tree")
    assert tree["tree"][0]["nodeKey"] == "root"
    assert tree["content"] == "Tải cây chủ đề phù hợp."
    query_analysis_rows = [
        row
        for row in rows
        if row.get("type") == "query_analysis" and row.get("content")
    ]
    assert query_analysis_rows[0]["content"] == "Phân tích câu hỏi của người dùng..."
    assert query_analysis_rows[-1]["content"] == "câu hỏi tra cứu đã chuẩn hóa"
    assert all("câu hỏi gốc" not in row["content"] for row in query_analysis_rows)
    assert any(row.get("type") == "corpus_traversal" for row in rows)
    traversal = next(row for row in rows if row.get("type") == "corpus_traversal")
    assert traversal == {
        "type": "corpus_traversal",
        "action": "select",
        "nodeKeys": ["root", "other"],
        "content": 'Chọn các chủ đề: "Gốc", "Khác".',
        "done": False,
    }
    traversal_end = next(row for row in rows if row.get("type") == "corpus_traversal_end")
    assert traversal_end == {
        "type": "corpus_traversal_end",
        "traversalComplete": True,
        "content": "Hoàn tất duyệt cây chủ đề.",
        "done": False,
    }
    assert any(row.get("content") == "Câu trả lời" for row in rows)
    final = rows[-1]
    assert final["done"] is True
    assert [step["type"] for step in final["steps"]].count("corpus_traversal") == 1
    assert any(step.get("type") == "corpus_tree" and step.get("tree") for step in final["steps"])
    assert "document_read" in [step["type"] for step in final["steps"]]
    assert final["tokenUsage"] == {"promptTokens": 1, "completionTokens": 2, "totalTokens": 3}
    assert final["sources"][0]["fileId"] == "file-1"
    assert "lecturerOnly" not in final["sources"][0]
    assert final["faqRecommendation"]["lecturerOnly"] is True
    assert final["faqRecommendation"]["metadata"] == {
        "enrollmentYear": {"fromYear": 2022, "toYear": 2022},
        "academicYear": {"fromYear": 0, "toYear": 9999},
    }
    assert fake_pipeline.requests[0].mode == "chat"
    assert fake_pipeline.requests[0].question == "q"
