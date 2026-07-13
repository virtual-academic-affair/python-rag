from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable

from google.genai import errors as genai_errors
from google.genai import types

from app.core.config import settings
from app.core.exceptions import CorpusTraversalError
from app.modules.corpus.contracts import TraversalResult
from app.modules.rag.query.retrieval.traversal.prompts import CORPUS_TRAVERSAL_PROMPT
from app.modules.rag.query.retrieval.traversal.contracts import FilteredCorpusSnapshot
from app.modules.rag.query.retrieval.traversal.runtime.activity import build_traversal_activity_step
from app.modules.rag.query.retrieval.traversal.tools import build_traversal_tools
from app.integrations.llm.gemini import gemini_client
from app.utils.retry import async_retry

logger = logging.getLogger(__name__)

_TERMINAL_TOOLS = {"select_topics", "select_no_match"}


def _upstream_status_code(exc: Exception) -> int:
    status_code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    return status_code if isinstance(status_code, int) and status_code in (429, 503) else 502


async def run_corpus_traversal(
    question: str,
    snapshot: FilteredCorpusSnapshot,
    max_turns: int | None = None,
    trace_id: str = "",
    on_step: Callable[[dict], Awaitable[None]] | None = None,
) -> TraversalResult:
    """Run a stateful LLM agent that explicitly navigates the filtered Corpus Tree."""
    max_turns = max_turns or settings.CORPUS_TRAVERSAL_MAX_TURNS
    tools = build_traversal_tools(snapshot)
    tool_map = {tool.__name__: tool for tool in tools}
    get_session = getattr(tools[0], "_get_session")

    config = types.GenerateContentConfig(
        system_instruction=CORPUS_TRAVERSAL_PROMPT,
        tools=tools,
        temperature=0.0,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )
    history = [
        types.Content(
            role="user",
            parts=[types.Part.from_text(text=f'Hãy tìm chủ đề liên quan đến câu hỏi: "{question}"')],
        )
    ]
    total_prompt_tokens = 0
    total_completion_tokens = 0
    activity_steps: list[dict] = []
    logger.info(
        "[RAG][%s][traversal.agent.start] max_turns=%d visible_roots=%d question=%r",
        trace_id,
        max_turns,
        len(snapshot.visible_root_keys),
        question[:300],
    )

    for turn_idx in range(max_turns):
        started_at = time.perf_counter()
        logger.info("[RAG][%s][traversal.turn.start] turn=%d", trace_id, turn_idx + 1)
        try:
            response = await async_retry(
                gemini_client.client.aio.models.generate_content,
                model=settings.CORPUS_TOPIC_MODEL or settings.GEMINI_MODEL,
                contents=history,
                config=config,
                retryable_exceptions=(genai_errors.ServerError,),
            )
        except Exception as exc:
            raise CorpusTraversalError(
                f"Corpus traversal LLM call failed: {exc}",
                status_code=_upstream_status_code(exc),
            ) from exc

        usage = getattr(response, "usage_metadata", None)
        if usage:
            total_prompt_tokens += getattr(usage, "prompt_token_count", 0) or 0
            total_completion_tokens += getattr(usage, "candidates_token_count", 0) or 0

        if not response.candidates or not response.candidates[0].content or not response.candidates[0].content.parts:
            raise CorpusTraversalError("Corpus traversal agent returned an empty response")

        model_parts = response.candidates[0].content.parts
        history.append(types.Content(role="model", parts=model_parts))
        tool_calls = [part.function_call for part in model_parts if part.function_call]
        if not tool_calls:
            raise CorpusTraversalError("Corpus traversal agent stopped without explicit selection")

        logger.info(
            "[RAG][%s][traversal.turn.tools] turn=%d calls=%s duration_ms=%d",
            trace_id,
            turn_idx + 1,
            [call.name for call in tool_calls],
            int((time.perf_counter() - started_at) * 1000),
        )

        terminal_calls = [call for call in tool_calls if call.name in _TERMINAL_TOOLS]
        tool_response_parts = []
        if terminal_calls and len(tool_calls) != 1:
            for call in tool_calls:
                tool_response_parts.append(
                    types.Part.from_function_response(
                        name=call.name,
                        response={"error": "A terminal selection/no-match tool must be the only call in its turn."},
                    )
                )
            history.append(types.Content(role="user", parts=tool_response_parts))
            continue

        for call in tool_calls:
            tool_func = tool_map.get(call.name)
            if tool_func is None:
                result: dict = {"status": "invalid", "reason": f"unknown tool: {call.name}"}
            else:
                try:
                    result = await tool_func(**dict(call.args))
                except Exception as exc:
                    raise CorpusTraversalError(
                        f"Corpus traversal tool '{call.name}' failed: {exc}",
                    ) from exc

            logger.info(
                "[RAG][%s][traversal.tool.result] turn=%d tool=%s status=%s result=%s",
                trace_id,
                turn_idx + 1,
                call.name,
                result.get("status") if isinstance(result, dict) else None,
                {
                    key: result.get(key)
                    for key in ("reason", "nodeKey", "totalFileCandidates", "totalFaqCandidates", "selectedTopics")
                    if isinstance(result, dict) and key in result
                },
            )

            tool_response_parts.append(
                types.Part.from_function_response(name=call.name, response={"result": result})
            )
            if isinstance(result, dict):
                activity_step = build_traversal_activity_step(snapshot, call.name, result)
                if activity_step is not None:
                    activity_steps.append(activity_step)
                    if on_step is not None:
                        await on_step(activity_step)
            status = result.get("status") if isinstance(result, dict) else None
            if call.name == "select_topics" and status == "selected":
                session = await get_session()
                traversal_result = TraversalResult(
                    status="selected",
                    file_candidates=session.file_candidates,
                    faq_candidates=session.faq_candidates,
                    selected_topics=session.selected_topics,
                    expanded_node_keys=session.expanded_node_keys,
                    inspected_node_keys=session.inspected_node_keys,
                    termination_reason="selected_topics",
                    turn_count=turn_idx + 1,
                    token_usage={
                        "prompt_tokens": total_prompt_tokens,
                        "completion_tokens": total_completion_tokens,
                        "total_tokens": total_prompt_tokens + total_completion_tokens,
                    },
                    steps=activity_steps,
                )
                logger.info(
                    "[RAG][%s][traversal.agent.selected] turns=%d files=%d faqs=%d tokens=%s",
                    trace_id,
                    traversal_result.turn_count,
                    len(traversal_result.file_candidates),
                    len(traversal_result.faq_candidates),
                    traversal_result.token_usage,
                )
                return traversal_result
            if call.name == "select_no_match" and status == "no_match":
                session = await get_session()
                traversal_result = TraversalResult(
                    status="no_match",
                    selected_topics=[],
                    expanded_node_keys=session.expanded_node_keys,
                    inspected_node_keys=session.inspected_node_keys,
                    termination_reason=str(result.get("reason") or "agent_no_match"),
                    turn_count=turn_idx + 1,
                    token_usage={
                        "prompt_tokens": total_prompt_tokens,
                        "completion_tokens": total_completion_tokens,
                        "total_tokens": total_prompt_tokens + total_completion_tokens,
                    },
                    steps=activity_steps,
                )
                logger.info(
                    "[RAG][%s][traversal.agent.no_match] turns=%d reason=%s",
                    trace_id,
                    traversal_result.turn_count,
                    traversal_result.termination_reason,
                )
                return traversal_result

        history.append(types.Content(role="user", parts=tool_response_parts))

    raise CorpusTraversalError(
        f"Corpus traversal agent reached max turns ({max_turns}) without explicit selection"
    )
