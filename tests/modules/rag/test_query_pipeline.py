import asyncio
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock, patch

import pytest

from app.modules.rag.query import RagQueryInput
from app.modules.rag.query.analyzer.contracts import ChatQueryAnalysis, EmailQueryAnalysis
from app.modules.rag.query.answering.faq_answering import (
    CHAT_FAQ_ANSWER_SYSTEM_PROMPT,
    EMAIL_FAQ_ANSWER_SYSTEM_PROMPT,
    FaqAnswerResult,
)
from app.modules.rag.query.answering.pageindex_agent import EMAIL_SYSTEM_PROMPT
from app.modules.rag.query.pipeline import RagQueryPipeline
from app.modules.rag.query.retrieval.retrieval_service import RetrievalSeeds


class FakeAnalyzer:
    def __init__(self, *, needs_rag=True, metadata_filter=None):
        self.needs_rag = needs_rag
        self.metadata_filter = metadata_filter
        self.analyze_query = AsyncMock(side_effect=self._analyze)
        self.generate_reply = AsyncMock(return_value=(
            "Trả lời trực tiếp",
            {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7},
        ))

    async def _analyze(self, question, _history):
        return ChatQueryAnalysis(
            effective_question=f"{question} effective",
            needs_rag=self.needs_rag,
            metadata_filter=self.metadata_filter,
            usage={"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
        )


class FakeEmailAnalyzer:
    def __init__(self, *, question="Câu hỏi email", metadata_filter=None, inquiry_types=None):
        self.analyze_email = AsyncMock(return_value=EmailQueryAnalysis(
            question=question,
            inquiry_types=inquiry_types or ["training"],
            metadata_filter=metadata_filter or {},
        ))


def _pipeline(
    analyzer=None,
    email_analyzer=None,
    file_candidates=None,
    faq_docs=None,
    candidate_files=None,
    faq_match=None,
):
    pipe = RagQueryPipeline()
    pipe._analyzer = analyzer or FakeAnalyzer()
    pipe._email_analyzer = email_analyzer or FakeEmailAnalyzer()
    pipe._retrieval = SimpleNamespace(
        traverse_query=AsyncMock(return_value=RetrievalSeeds(
            file_candidates=file_candidates or [],
            faq_candidates=["faq-seed"] if faq_docs else [],
        )),
        retrieve_faq_context=AsyncMock(return_value=faq_docs or []),
        retrieve_file_context=AsyncMock(return_value=candidate_files or []),
    )
    faq_answer = None
    if faq_match:
        answer_markdown = "Câu trả lời FAQ do LLM tổng hợp"
        faq_answer = FaqAnswerResult(
            answer_markdown=answer_markdown,
            matched_faqs=faq_match,
            token_usage={"prompt_tokens": 8, "completion_tokens": 4, "total_tokens": 12},
        )
    pipe._faq_answer_service = SimpleNamespace(
        answer=AsyncMock(return_value=faq_answer)
    )
    return pipe


@pytest.mark.asyncio
async def test_answer_chat_uses_common_engine_with_analyzer_enrollment_fallback():
    pipe = _pipeline(
        analyzer=FakeAnalyzer(metadata_filter={}),
        file_candidates=["file-seed"],
        candidate_files=[{"file_id": "f1", "file_name": "Quy chế", "doc_description": "Mô tả"}],
    )
    agent_mock = AsyncMock(return_value={
        "final_answer": "Câu trả lời tài liệu",
        "sources": [],
        "steps": [{"type": "call", "name": "get_document_structure", "args": {"file_id": "1"}}],
        "tokenUsage": {"promptTokens": 10, "completionTokens": 5, "totalTokens": 15},
        "max_turns_reached": False,
    })

    with patch("app.modules.rag.query.pipeline.run_pageindex_agent_loop", agent_mock):
        result = await pipe.answer_chat(RagQueryInput(
            mode="chat",
            question="Chuẩn ngoại ngữ?",
            user_role="student",
            enrollment_year=2022,
        ))

    pipe._retrieval.traverse_query.assert_awaited_once_with(
        question="Chuẩn ngoại ngữ? effective",
        metadata_filter={"enrollment_year": {"from_year": 2022, "to_year": 2022}},
        user_role="student",
        trace_id=ANY,
        include_reasoning=True,
    )
    pipe._retrieval.retrieve_file_context.assert_awaited_once_with(
        "Chuẩn ngoại ngữ? effective",
        ["file-seed"],
        trace_id=ANY,
    )
    assert result.answer_markdown == "Câu trả lời tài liệu"
    assert result.analysis.effective_question == "Chuẩn ngoại ngữ? effective"
    assert [s["type"] for s in result.steps] == ["query_analysis", "file_retrieval", "call"]
    pipe._retrieval.retrieve_faq_context.assert_not_awaited()


@pytest.mark.asyncio
async def test_answer_chat_direct_reply_does_not_retrieve():
    pipe = _pipeline(analyzer=FakeAnalyzer(needs_rag=False))

    result = await pipe.answer_chat(RagQueryInput(
        mode="chat",
        question="Xin chào",
        user_role="student",
    ))

    pipe._retrieval.traverse_query.assert_not_awaited()
    pipe._retrieval.retrieve_faq_context.assert_not_awaited()
    pipe._retrieval.retrieve_file_context.assert_not_awaited()
    assert result.is_direct_reply is True
    assert result.answer_markdown == "Trả lời trực tiếp"
    assert result.token_usage == {"prompt_tokens": 4, "completion_tokens": 6, "total_tokens": 10}


@pytest.mark.asyncio
async def test_answer_chat_uses_faq_match_without_reading_pageindex():
    faq = SimpleNamespace(
        id="faq1",
        question="Chuẩn ngoại ngữ K22?",
        answer_markdown="Câu trả lời từ FAQ",
        lecturer_only=False,
    )
    unmatched_restricted_faq = SimpleNamespace(
        id="faq2",
        question="FAQ nội bộ không được dùng",
        answer_markdown="Thông tin nội bộ",
        lecturer_only=True,
    )
    pipe = _pipeline(
        analyzer=FakeAnalyzer(metadata_filter={}),
        file_candidates=["file-seed"],
        faq_docs=[faq, unmatched_restricted_faq],
        faq_match=[faq],
    )
    agent_mock = AsyncMock()

    with patch("app.modules.rag.query.pipeline.run_pageindex_agent_loop", agent_mock):
        result = await pipe.answer_chat(RagQueryInput(
            mode="chat",
            question="Chuẩn ngoại ngữ K22?",
            user_role="student",
        ))

    agent_mock.assert_not_awaited()
    pipe._retrieval.retrieve_faq_context.assert_awaited_once()
    pipe._retrieval.retrieve_file_context.assert_not_awaited()
    pipe._faq_answer_service.answer.assert_awaited_once_with(
        "Chuẩn ngoại ngữ K22? effective",
        [faq, unmatched_restricted_faq],
        system_prompt=CHAT_FAQ_ANSWER_SYSTEM_PROMPT,
    )
    assert result.source == "faq"
    assert result.answer_markdown == "Câu trả lời FAQ do LLM tổng hợp"
    assert result.token_usage == {"prompt_tokens": 8, "completion_tokens": 4, "total_tokens": 12}
    assert result.used_faq_docs == [faq]
    assert [s["type"] for s in result.steps] == ["query_analysis", "faq_retrieval", "faq_answer"]


@pytest.mark.asyncio
async def test_stream_chat_emits_common_pipeline_events_and_agent_events():
    pipe = _pipeline(
        analyzer=FakeAnalyzer(metadata_filter={}),
        file_candidates=["file-seed"],
        candidate_files=[{"file_id": "f1", "file_name": "Quy chế", "doc_description": "Mô tả"}],
    )

    async def fake_stream_pageindex_agent_loop(**_kwargs):
        yield {"type": "call", "step": {"type": "call", "name": "get_document_structure", "args": {"file_id": "1"}}}
        yield {"type": "text", "content": "Câu trả lời", "done": False}
        yield {
            "type": "_agent_result",
            "final_answer": "Câu trả lời",
            "max_turns_reached": False,
            "steps": [],
            "sources": [],
            "token_usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }

    with patch("app.modules.rag.query.pipeline.stream_pageindex_agent_loop", fake_stream_pageindex_agent_loop):
        events = [
            event
            async for event in pipe.stream_chat(RagQueryInput(
                mode="chat",
                question="q",
                user_role="student",
            ))
        ]

    assert [events[0]["type"], events[1]["type"], events[2]["type"]] == [
        "_query_analysis_start",
        "_query_analysis",
        "_pipeline_step",
    ]
    pipe._retrieval.retrieve_faq_context.assert_not_awaited()
    assert any(event.get("type") == "call" for event in events)
    assert any(event.get("type") == "_agent_result" for event in events)


@pytest.mark.asyncio
async def test_stream_chat_emits_corpus_steps_before_traversal_finishes():
    pipe = _pipeline(analyzer=FakeAnalyzer(metadata_filter={}))
    release_traversal = asyncio.Event()

    async def traverse_query(**kwargs):
        await kwargs["on_traversal_step"]({
            "type": "corpus_tree",
            "content": "Đã tải cây chủ đề phù hợp.",
            "tree": [{"nodeKey": "root", "title": "Gốc", "summary": "", "children": []}],
        })
        await kwargs["on_traversal_step"]({
            "type": "corpus_traversal",
            "action": "expand",
            "node_key": "root",
            "content": "Đã mở chủ đề Gốc.",
        })
        await release_traversal.wait()
        return RetrievalSeeds()

    pipe._retrieval.traverse_query = traverse_query
    stream = pipe.stream_chat(RagQueryInput(mode="chat", question="q", user_role="student"))

    assert (await anext(stream))["type"] == "_query_analysis_start"
    assert (await anext(stream))["type"] == "_query_analysis"
    tree_event = await anext(stream)
    assert tree_event == {
        "type": "_corpus_tree",
        "content": "Đã tải cây chủ đề phù hợp.",
        "tree": [{"nodeKey": "root", "title": "Gốc", "summary": "", "children": []}],
    }
    corpus_event = await anext(stream)
    assert corpus_event == {
        "type": "_corpus_traversal",
        "step": {
            "type": "corpus_traversal",
            "action": "expand",
            "node_key": "root",
            "content": "Đã mở chủ đề Gốc.",
        },
    }

    release_traversal.set()
    remaining = [event async for event in stream]
    assert any(event.get("type") == "_pipeline_step" for event in remaining)


@pytest.mark.asyncio
async def test_stream_chat_uses_faq_pipeline_result_without_agent_events():
    faq = SimpleNamespace(
        id="faq1",
        question="Chuẩn ngoại ngữ K22?",
        answer_markdown="Câu trả lời từ FAQ",
    )
    pipe = _pipeline(
        analyzer=FakeAnalyzer(metadata_filter={}),
        faq_docs=[faq],
        faq_match=[faq],
    )

    async def fake_stream_pageindex_agent_loop(**_kwargs):
        yield {"type": "text", "content": "Không nên chạy", "done": False}

    with patch("app.modules.rag.query.pipeline.stream_pageindex_agent_loop", fake_stream_pageindex_agent_loop):
        events = [
            event
            async for event in pipe.stream_chat(RagQueryInput(
                mode="chat",
                question="q",
                user_role="student",
            ))
        ]

    final = events[-1]
    assert final["type"] == "_pipeline_result"
    assert final["source"] == "faq"
    assert final["answer_markdown"] == "Câu trả lời FAQ do LLM tổng hợp"
    assert final["token_usage"] == {"prompt_tokens": 8, "completion_tokens": 4, "total_tokens": 12}
    assert final["used_faq_docs"] == [faq]
    assert [s["type"] for s in final["steps"]] == ["query_analysis", "faq_retrieval", "faq_answer"]
    pipe._retrieval.retrieve_file_context.assert_not_awaited()


@pytest.mark.asyncio
async def test_answer_chat_can_use_multiple_faqs_for_multi_intent_question():
    faq_1 = SimpleNamespace(
        id="faq1",
        question="Chuẩn ngoại ngữ K22?",
        answer_markdown="Câu trả lời ngoại ngữ",
    )
    faq_2 = SimpleNamespace(
        id="faq2",
        question="Thủ tục xét tốt nghiệp?",
        answer_markdown="Câu trả lời xét tốt nghiệp",
    )
    pipe = _pipeline(
        analyzer=FakeAnalyzer(metadata_filter={}),
        faq_docs=[faq_1, faq_2],
        faq_match=[faq_1, faq_2],
    )

    result = await pipe.answer_chat(RagQueryInput(
        mode="chat",
        question="Chuẩn ngoại ngữ K22 và thủ tục xét tốt nghiệp?",
        user_role="student",
    ))

    assert result.source == "faq"
    assert result.answer_markdown == "Câu trả lời FAQ do LLM tổng hợp"
    assert result.steps[-1]["faq_ids"] == ["faq1", "faq2"]


@pytest.mark.asyncio
async def test_answer_email_skips_chat_analyzer_and_uses_shared_citation_behavior():
    analyzer = FakeAnalyzer()
    email_analyzer = FakeEmailAnalyzer(
        question="Câu hỏi email normalized",
        metadata_filter={"enrollment_year": {"from_year": 2022, "to_year": 2022}},
    )
    pipe = _pipeline(
        analyzer=analyzer,
        email_analyzer=email_analyzer,
        file_candidates=["file-seed"],
        candidate_files=[{"file_id": "f1", "file_name": "Quy chế", "doc_description": "Mô tả"}],
    )
    agent_mock = AsyncMock(return_value={
        "final_answer": "Email answer",
        "sources": [],
        "steps": [],
        "tokenUsage": None,
        "max_turns_reached": False,
    })

    with patch("app.modules.rag.query.pipeline.run_pageindex_agent_loop", agent_mock):
        result = await pipe.answer_email(RagQueryInput(
            mode="email",
            question="Câu hỏi email",
            user_role="student",
            metadata_filter={"enrollment_year": {"from_year": 2022, "to_year": 2022}},
            email_subject="Tiêu đề",
            email_content="Nội dung",
        ))

    analyzer.analyze_query.assert_not_awaited()
    email_analyzer.analyze_email.assert_awaited_once_with("Tiêu đề", "Nội dung", sender_enrollment_year=None)
    pipe._retrieval.traverse_query.assert_awaited_once_with(
        question="Câu hỏi email normalized",
        metadata_filter={"enrollment_year": {"from_year": 2022, "to_year": 2022}},
        user_role="student",
        trace_id=ANY,
        include_reasoning=False,
    )
    _, kwargs = agent_mock.call_args
    assert "citation_link_type" not in kwargs
    assert "resolve_citations" not in kwargs
    assert kwargs["system_prompt"] == EMAIL_SYSTEM_PROMPT
    assert result.answer_markdown == "Email answer"
    assert result.analysis.effective_question == "Câu hỏi email normalized"
    assert result.analysis.metadata_filter == {"enrollment_year": {"from_year": 2022, "to_year": 2022}}


@pytest.mark.asyncio
async def test_answer_email_can_return_faq_token_usage():
    faq = SimpleNamespace(
        id="faq1",
        question="Chuẩn ngoại ngữ?",
        answer_markdown="Câu trả lời FAQ",
    )
    pipe = _pipeline(
        email_analyzer=FakeEmailAnalyzer(question="Chuẩn ngoại ngữ?"),
        faq_docs=[faq],
        faq_match=[faq],
    )

    result = await pipe.answer_email(RagQueryInput(
        mode="email",
        question="Chuẩn ngoại ngữ?",
        user_role="student",
    ))

    assert result.source == "faq"
    assert result.token_usage == {"prompt_tokens": 8, "completion_tokens": 4, "total_tokens": 12}
    pipe._retrieval.retrieve_file_context.assert_not_awaited()
    pipe._faq_answer_service.answer.assert_awaited_once_with(
        "Chuẩn ngoại ngữ?",
        [faq],
        system_prompt=EMAIL_FAQ_ANSWER_SYSTEM_PROMPT,
    )


@pytest.mark.asyncio
async def test_no_candidate_fallback_differs_between_chat_and_email():
    chat_pipe = _pipeline(analyzer=FakeAnalyzer(metadata_filter={}))
    email_pipe = _pipeline(email_analyzer=FakeEmailAnalyzer(question="q"))

    chat_result = await chat_pipe.answer_chat(RagQueryInput(
        mode="chat",
        question="q",
        user_role="student",
    ))
    email_result = await email_pipe.answer_email(RagQueryInput(
        mode="email",
        question="q",
        user_role="student",
    ))

    assert chat_result.source == "bypass"
    assert chat_result.answer_markdown == "Không tìm thấy tài liệu nào phù hợp với yêu cầu của bạn."
    assert email_result.source == "bypass"
    assert email_result.answer_markdown == "Không tìm thấy tài liệu phù hợp để trả lời email này."
