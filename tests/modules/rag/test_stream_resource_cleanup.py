import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.modules.rag.query import RagQueryInput
from app.modules.rag.query.analyzer.contracts import ChatQueryAnalysis
from app.modules.rag.query.pipeline import RagQueryPipeline


@pytest.mark.asyncio
async def test_stream_cancellation_cleans_queue_waiter_and_traversal_task():
    pipeline = RagQueryPipeline()
    pipeline._analyzer = SimpleNamespace(
        analyze_query=AsyncMock(return_value=ChatQueryAnalysis(
            effective_question="question",
            needs_rag=True,
            metadata_filter={},
        ))
    )
    traversal_started = asyncio.Event()
    traversal_cancelled = asyncio.Event()

    async def traverse_query(**_kwargs):
        traversal_started.set()
        try:
            await asyncio.Event().wait()
        finally:
            traversal_cancelled.set()

    pipeline._retrieval = SimpleNamespace(traverse_query=traverse_query)
    stream = pipeline.stream_chat(RagQueryInput(
        mode="chat",
        question="question",
        user_role="student",
    ))

    assert (await anext(stream))["type"] == "_query_analysis_start"
    assert (await anext(stream))["type"] == "_query_analysis"

    pending_event = asyncio.create_task(anext(stream), name="test-stream-consumer")
    await traversal_started.wait()
    await asyncio.sleep(0)
    resource_tasks = [
        task
        for task in asyncio.all_tasks()
        if task.get_name().startswith("rag-traversal")
    ]
    assert {task.get_name().split(":", 1)[0] for task in resource_tasks} == {
        "rag-traversal",
        "rag-traversal-step",
    }

    pending_event.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending_event
    await asyncio.wait_for(traversal_cancelled.wait(), timeout=1)
    await asyncio.sleep(0)

    assert all(task.done() for task in resource_tasks)
