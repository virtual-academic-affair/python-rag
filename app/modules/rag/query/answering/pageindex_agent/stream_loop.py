from __future__ import annotations

import logging
import re
import time
from typing import Any, AsyncGenerator

from app.core.config import settings
from app.integrations.llm.contracts import LLMStreamAccumulator
from app.integrations.llm.gateway import get_llm_gateway
from app.modules.rag.query.answering.pageindex_agent.citations import (
    CitationStreamFormatter,
    build_sources_from_steps,
)
from app.modules.rag.query.answering.pageindex_agent.loop import get_agent_config
from app.modules.rag.query.answering.pageindex_agent.parser import parse_agent_response
from app.modules.rag.query.answering.pageindex_agent.prompts import CHAT_SYSTEM_PROMPT
from app.utils.format_utils import sanitize_latex_in_markdown

logger = logging.getLogger(__name__)


async def stream_pageindex_agent_loop(
    *,
    candidate_files: list[dict],
    prompt_contents: Any,
    system_prompt: str = CHAT_SYSTEM_PROMPT,
    include_reasoning: bool = True,
    trace_id: str = "",
) -> AsyncGenerator[dict, None]:
    """
    Stream the PageIndex agent loop.

    Yields public SSE-ready reasoning/text events, raw call steps for caller-side
    formatting, and a final internal `_agent_result` event with sources/steps/usage.
    """
    tools, tool_map = get_agent_config(
        candidate_files,
        system_prompt=system_prompt,
        include_reasoning=include_reasoning,
    )

    if isinstance(prompt_contents, str):
        history = [{"role": "user", "content": prompt_contents}]
    elif isinstance(prompt_contents, dict):
        history = [prompt_contents]
    else:
        history = list(prompt_contents)
    history.insert(0, {"role": "system", "content": system_prompt})
    llm_gateway = get_llm_gateway()

    stream_steps: list[dict] = []
    stream_formatter: CitationStreamFormatter | None = None
    current_sources: list[dict] | None = None
    total_prompt_tokens = 0
    total_candidates_tokens = 0
    final_answer_accumulated = ""
    start_agent = time.perf_counter()
    last_turn_idx = -1
    last_tool_calls: list[Any] = []

    logger.info(
        "[RAG][%s][pageindex.stream.start] max_turns=%d candidates=%s",
        trace_id,
        settings.PAGEINDEX_AGENT_MAX_TURNS,
        [file.get("file_id") for file in candidate_files],
    )

    for turn_idx in range(settings.PAGEINDEX_AGENT_MAX_TURNS):
        last_turn_idx = turn_idx
        start_turn = time.perf_counter()
        turn_text_buffer = ""
        in_answer_block = False
        yielded_text_length = 0
        accumulator = LLMStreamAccumulator()

        async for chunk in llm_gateway.stream(
            model=settings.LLM_MODEL,
            messages=history,
            temperature=settings.LLM_DETERMINISTIC_TEMPERATURE,
            tools=tools,
        ):
            accumulator.add(chunk)
            if not chunk.text_delta:
                continue

            turn_text_buffer += chunk.text_delta
            if not in_answer_block:
                match = re.search(r"<answer>", turn_text_buffer, flags=re.IGNORECASE)
                if match:
                    pre_think = turn_text_buffer[:match.start()].strip()
                    if pre_think:
                        logger.debug("[RAG][%s][pageindex.stream.reasoning] text=%r", trace_id, pre_think[:300])
                        stream_steps.append({"type": "conclude", "content": pre_think})
                    in_answer_block = True

            if in_answer_block:
                if stream_formatter is None:
                    current_sources = await build_sources_from_steps(stream_steps, candidate_files)
                    stream_formatter = CitationStreamFormatter(current_sources)

                match = re.search(r"<answer>\r?\n?(.*)", turn_text_buffer, flags=re.DOTALL | re.IGNORECASE)
                if match:
                    inside_content = match.group(1)
                    end_match = re.search(r"</answer>", inside_content, flags=re.IGNORECASE)
                    if end_match:
                        final_to_yield = inside_content[:end_match.start()]
                        new_text = final_to_yield[yielded_text_length:]
                        if new_text:
                            formatted = stream_formatter.process_chunk(new_text)
                            formatted_flush = stream_formatter.flush()
                            combined = formatted + formatted_flush
                            if combined:
                                final_answer_accumulated += combined
                                yield {"type": "text", "content": combined, "done": False}
                            yielded_text_length += len(new_text)
                    else:
                        safe_len = len(inside_content) - 15
                        if safe_len > yielded_text_length:
                            new_text = inside_content[yielded_text_length:safe_len]
                            formatted = stream_formatter.process_chunk(new_text)
                            if formatted:
                                final_answer_accumulated += formatted
                                yield {"type": "text", "content": formatted, "done": False}
                            yielded_text_length += len(new_text)

        model_response = accumulator.response()
        tool_calls_in_turn = model_response.tool_calls
        turn_prompt_tokens = model_response.usage.prompt_tokens if model_response.usage else 0
        turn_candidates_tokens = model_response.usage.completion_tokens if model_response.usage else 0

        for call in tool_calls_in_turn:
            args = dict(call.arguments)
            reason_val = args.pop("reasoning", None)
            if reason_val:
                yield {"type": "reasoning", "content": f"{reason_val}\n", "done": False}
                stream_steps.append({"type": "reasoning", "content": reason_val})

            call_step = {"type": "call", "name": call.name, "args": args}
            stream_steps.append(call_step)
            yield {"type": "call", "step": call_step, "done": False}

        if not tool_calls_in_turn and turn_text_buffer and in_answer_block:
            _pre_think, final_text = parse_agent_response(turn_text_buffer)
            if len(final_text) > yielded_text_length:
                new_text = final_text[yielded_text_length:]
                if stream_formatter is None:
                    current_sources = await build_sources_from_steps(stream_steps, candidate_files)
                    stream_formatter = CitationStreamFormatter(current_sources)

                formatted = stream_formatter.process_chunk(new_text)
                formatted_flush = stream_formatter.flush()
                combined = formatted + formatted_flush
                if combined:
                    final_answer_accumulated += combined
                    yield {"type": "text", "content": combined, "done": False}

        history.append(model_response.assistant_message)

        total_prompt_tokens += turn_prompt_tokens
        total_candidates_tokens += turn_candidates_tokens
        logger.info(
            "[RAG][%s][pageindex.stream.turn] turn=%d duration_ms=%d tool_calls=%d tokens=%d/%d",
            trace_id,
            turn_idx + 1,
            int((time.perf_counter() - start_turn) * 1000),
            len(tool_calls_in_turn),
            turn_prompt_tokens,
            turn_candidates_tokens,
        )

        if not tool_calls_in_turn:
            last_tool_calls = []
            break

        tool_response_messages = []
        for call in tool_calls_in_turn:
            try:
                tool_func = tool_map.get(call.name)
                logger.info(
                    "[RAG][%s][pageindex.stream.tool.call] turn=%d tool=%s args=%s",
                    trace_id,
                    turn_idx + 1,
                    call.name,
                    call.arguments,
                )
                tool_started_at = time.perf_counter()
                result = await tool_func(**call.arguments) if tool_func else f"Error: Tool {call.name} not found."
                logger.info(
                    "[RAG][%s][pageindex.stream.tool.result] turn=%d tool=%s duration_ms=%d result=%s",
                    trace_id,
                    turn_idx + 1,
                    call.name,
                    int((time.perf_counter() - tool_started_at) * 1000),
                    str(result)[:500],
                )
                tool_response_messages.append({
                    "role": "tool",
                    "tool_call_id": call.id,
                    "name": call.name,
                    "content": str(result),
                })
            except Exception as e:
                logger.exception(
                    "[RAG][%s][pageindex.stream.tool.error] turn=%d tool=%s",
                    trace_id,
                    turn_idx + 1,
                    call.name,
                )
                tool_response_messages.append({
                    "role": "tool",
                    "tool_call_id": call.id,
                    "name": call.name,
                    "content": f"Error: {e}",
                })

        history.extend(tool_response_messages)
        last_tool_calls = tool_calls_in_turn

    if current_sources is None:
        current_sources = await build_sources_from_steps(stream_steps, candidate_files)

    max_turns_reached = last_turn_idx == settings.PAGEINDEX_AGENT_MAX_TURNS - 1 and bool(last_tool_calls)
    if max_turns_reached:
        logger.warning(
            "[RAG][%s][pageindex.stream.max_turns] max_turns=%d",
            trace_id,
            settings.PAGEINDEX_AGENT_MAX_TURNS,
        )

    final_answer_accumulated = sanitize_latex_in_markdown(final_answer_accumulated)
    if not final_answer_accumulated:
        fallback_text = "Hệ thống chưa tổng hợp được câu trả lời từ tài liệu. Vui lòng hỏi lại cụ thể hơn."
        logger.warning("[RAG][%s][pageindex.stream.empty_answer] fallback=true", trace_id)
        yield {"type": "text", "content": fallback_text, "done": False}
        final_answer_accumulated = fallback_text

    logger.info(
        "[RAG][%s][pageindex.stream.complete] duration_ms=%d turns=%d sources=%d max_turns=%s tokens=%d/%d",
        trace_id,
        int((time.perf_counter() - start_agent) * 1000),
        last_turn_idx + 1,
        len(current_sources or []),
        max_turns_reached,
        total_prompt_tokens,
        total_candidates_tokens,
    )

    yield {
        "type": "_agent_result",
        "final_answer": final_answer_accumulated,
        "max_turns_reached": max_turns_reached,
        "steps": stream_steps,
        "sources": current_sources or [],
        "token_usage": {
            "prompt_tokens": total_prompt_tokens,
            "completion_tokens": total_candidates_tokens,
            "total_tokens": total_prompt_tokens + total_candidates_tokens,
        },
    }
