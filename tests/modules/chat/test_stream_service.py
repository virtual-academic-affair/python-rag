import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.chat.dtos import ChatHistoryItem, UserContext
from app.modules.chat.services.chat_stream_service import ChatStreamService
from app.modules.rag.query import RagQueryInput


async def _collect(generator):
    rows = []
    async for item in generator:
        rows.append(json.loads(item))
    return rows


@pytest.mark.asyncio
async def test_chat_stream_service_formats_agent_events_and_final_payload():
    svc = ChatStreamService.__new__(ChatStreamService)
    svc._get_faq_svc = AsyncMock(return_value=MagicMock(log_interaction=AsyncMock()))

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
                    "original_question": "q",
                    "effective_question": "q",
                    "needs_rag": True,
                    "metadata_filter": {},
                },
            }
            yield {
                "type": "_corpus_traversal",
                "step": {
                    "type": "corpus_traversal",
                    "action": "list_roots",
                    "topic_count": 2,
                },
            }
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
            "sources": [],
                "token_usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
            }

    fake_pipeline = FakePipeline()
    svc._rag_query = fake_pipeline

    def close_background_coro(coro):
        coro.close()

    with patch("app.modules.chat.services.chat_stream_service.fire_and_forget", side_effect=close_background_coro):
        rows = await _collect(svc.stream_chat_response(
            "q",
            UserContext(user_id="u1", name="User", role="student"),
            [ChatHistoryItem(role="user", content="q")],
        ))

    assert any(row.get("content") == "Đang tra cứu cấu trúc mục lục của 'Quy chế'." for row in rows)
    assert any(row.get("type") == "corpus_traversal" for row in rows)
    assert any(row.get("content") == "Câu trả lời" for row in rows)
    final = rows[-1]
    assert final["done"] is True
    assert [step["type"] for step in final["steps"]].count("corpus_traversal") == 1
    assert "document_read" in [step["type"] for step in final["steps"]]
    assert final["tokenUsage"] == {"promptTokens": 1, "completionTokens": 2, "totalTokens": 3}
    assert final["sources"] == []
    assert fake_pipeline.requests[0].mode == "chat"
    assert fake_pipeline.requests[0].question == "q"
