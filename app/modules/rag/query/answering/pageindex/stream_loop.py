from __future__ import annotations

import logging
import re
import time
from typing import Any, AsyncGenerator

from google.genai import types
from google.genai import errors as genai_errors

from app.core.config import settings
from app.integrations.llm.gemini import gemini_client
from app.modules.rag.query.answering.pageindex.citation import CitationStreamFormatter, build_sources_from_steps
from app.modules.rag.query.answering.pageindex.loop import get_agent_config
from app.modules.rag.query.answering.pageindex.parser import parse_agent_response
from app.modules.rag.query.answering.pageindex.prompts import CHAT_SYSTEM_PROMPT
from app.utils.format_utils import sanitize_latex_in_markdown
from app.utils.retry import async_retry

logger = logging.getLogger(__name__)


async def stream_agent_loop(
    *,
    candidate_files: list[dict],
    prompt_contents: Any,
    resolve_citations: bool = False,
    citation_link_type: str = "markdown",
    system_prompt: str = CHAT_SYSTEM_PROMPT,
    include_reasoning: bool = True,
) -> AsyncGenerator[dict, None]:
    """
    Stream the PageIndex agent loop.

    Yields public SSE-ready reasoning/text events, raw call steps for caller-side
    formatting, and a final internal `_agent_result` event with sources/steps/usage.
    """
    tools, tool_map, config = get_agent_config(
        candidate_files,
        system_prompt=system_prompt,
        include_reasoning=include_reasoning,
    )

    if isinstance(prompt_contents, str):
        history = [types.Content(role="user", parts=[types.Part.from_text(text=prompt_contents)])]
    elif isinstance(prompt_contents, types.Content):
        history = [prompt_contents]
    else:
        history = list(prompt_contents)

    stream_steps: list[dict] = []
    stream_formatter: CitationStreamFormatter | None = None
    current_sources: list[dict] | None = None
    total_prompt_tokens = 0
    total_candidates_tokens = 0
    final_answer_accumulated = ""
    start_agent = time.perf_counter()
    last_turn_idx = -1
    last_tool_calls: list[Any] = []

    logger.info("[Chat-Stream] Agent started")

    for turn_idx in range(settings.AGENT_MAX_TURNS):
        last_turn_idx = turn_idx
        start_turn = time.perf_counter()
        tool_calls_in_turn = []
        model_response_parts = []
        turn_text_buffer = ""
        in_answer_block = False
        yielded_text_length = 0

        stream = await async_retry(
            gemini_client.client.aio.models.generate_content_stream,
            model=settings.GEMINI_MODEL,
            contents=history,
            config=config,
            retryable_exceptions=(genai_errors.ServerError,),
        )

        turn_prompt_tokens = 0
        turn_candidates_tokens = 0

        async for chunk in stream:
            if hasattr(chunk, "usage_metadata") and chunk.usage_metadata:
                turn_prompt_tokens = getattr(chunk.usage_metadata, "prompt_token_count", 0) or 0
                turn_candidates_tokens = getattr(chunk.usage_metadata, "candidates_token_count", 0) or 0

            if not chunk.candidates or not chunk.candidates[0].content or not chunk.candidates[0].content.parts:
                continue
            for part in chunk.candidates[0].content.parts:
                model_response_parts.append(part)

                if hasattr(part, "thought") and part.thought:
                    continue

                if part.function_call:
                    call = part.function_call
                    tool_calls_in_turn.append(call)

                    args = dict(call.args)
                    reason_val = args.pop("reasoning", None)
                    if reason_val:
                        yield {"type": "reasoning", "content": f"{reason_val}\n", "done": False}
                        stream_steps.append({"type": "reasoning", "content": reason_val})

                    call_step = {"type": "call", "name": call.name, "args": args}
                    stream_steps.append(call_step)
                    yield {"type": "call", "step": call_step, "done": False}

                if part.text:
                    turn_text_buffer += part.text
                    if not in_answer_block:
                        match = re.search(r"<answer>", turn_text_buffer, flags=re.IGNORECASE)
                        if match:
                            pre_think = turn_text_buffer[:match.start()].strip()
                            if pre_think:
                                logger.info("[Chat-Stream] Conclude/Pre-answer reasoning: %s...", pre_think[:100])
                                stream_steps.append({"type": "conclude", "content": pre_think})
                            in_answer_block = True

                    if in_answer_block:
                        if stream_formatter is None:
                            current_sources = await build_sources_from_steps(stream_steps, candidate_files)
                            stream_formatter = CitationStreamFormatter(
                                current_sources,
                                resolve_citations=resolve_citations,
                                citation_link_type=citation_link_type,
                            )

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

        if not tool_calls_in_turn and turn_text_buffer and in_answer_block:
            _pre_think, final_text = parse_agent_response(turn_text_buffer)
            if len(final_text) > yielded_text_length:
                new_text = final_text[yielded_text_length:]
                if stream_formatter is None:
                    current_sources = await build_sources_from_steps(stream_steps, candidate_files)
                    stream_formatter = CitationStreamFormatter(
                        current_sources,
                        resolve_citations=resolve_citations,
                        citation_link_type=citation_link_type,
                    )

                formatted = stream_formatter.process_chunk(new_text)
                formatted_flush = stream_formatter.flush()
                combined = formatted + formatted_flush
                if combined:
                    final_answer_accumulated += combined
                    yield {"type": "text", "content": combined, "done": False}

        clean_parts = []
        current_text_segments = []
        for part in model_response_parts:
            if part.text:
                current_text_segments.append(part.text)
            else:
                if current_text_segments:
                    clean_parts.append(types.Part.from_text(text="".join(current_text_segments)))
                    current_text_segments = []
                clean_parts.append(part)
        if current_text_segments:
            clean_parts.append(types.Part.from_text(text="".join(current_text_segments)))
        history.append(types.Content(role="model", parts=clean_parts))

        total_prompt_tokens += turn_prompt_tokens
        total_candidates_tokens += turn_candidates_tokens
        logger.info(
            "[Chat-Stream] === Turn %s done in %.2fs | tool_calls=%s | tokens(%s/%s)",
            turn_idx + 1,
            time.perf_counter() - start_turn,
            len(tool_calls_in_turn),
            turn_prompt_tokens,
            turn_candidates_tokens,
        )

        if not tool_calls_in_turn:
            last_tool_calls = []
            break

        tool_response_parts = []
        for call in tool_calls_in_turn:
            try:
                tool_func = tool_map.get(call.name)
                result = await tool_func(**call.args) if tool_func else f"Error: Tool {call.name} not found."
                tool_response_parts.append(
                    types.Part.from_function_response(name=call.name, response={"result": result})
                )
            except Exception as e:
                logger.error("[Chat-Stream] Tool '%s' failed at turn %s: %s", call.name, turn_idx + 1, e, exc_info=True)
                tool_response_parts.append(
                    types.Part.from_function_response(name=call.name, response={"error": str(e)})
                )

        history.append(types.Content(role="user", parts=tool_response_parts))
        last_tool_calls = tool_calls_in_turn

    if current_sources is None:
        current_sources = await build_sources_from_steps(stream_steps, candidate_files)

    max_turns_reached = last_turn_idx == settings.AGENT_MAX_TURNS - 1 and bool(last_tool_calls)
    if max_turns_reached:
        logger.warning("[Chat-Stream] Agent reached max_turns (%s) and was cut off.", settings.AGENT_MAX_TURNS)

    final_answer_accumulated = sanitize_latex_in_markdown(final_answer_accumulated)
    if not final_answer_accumulated:
        fallback_text = "Hệ thống chưa tổng hợp được câu trả lời từ tài liệu. Vui lòng hỏi lại cụ thể hơn."
        logger.warning("[Chat-Stream] Empty final_answer_accumulated. Emitting fallback.")
        yield {"type": "text", "content": fallback_text, "done": False}
        final_answer_accumulated = fallback_text

    logger.info(
        "[Chat-Stream] Agent Loop done in %.2fs | turns=%s | Usage: %s prompt / %s completion",
        time.perf_counter() - start_agent,
        last_turn_idx + 1,
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
