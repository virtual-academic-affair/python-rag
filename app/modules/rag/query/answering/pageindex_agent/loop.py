import logging
import time
from typing import List, Callable, Any
from google.genai import types
from google.genai import errors as genai_errors

from app.core.config import settings
from app.integrations.llm.gemini import gemini_client
from app.utils.format_utils import sanitize_latex_in_markdown
from app.utils.retry import async_retry
from app.modules.rag.query.answering.pageindex_agent.prompts import CHAT_SYSTEM_PROMPT
from app.modules.rag.query.answering.pageindex_agent.tools import build_pageindex_tools
from app.modules.rag.query.answering.pageindex_agent.citations import (
    build_sources_from_steps,
    verify_citations,
)
from app.modules.rag.query.answering.pageindex_agent.parser import parse_agent_response

logger = logging.getLogger(__name__)

def get_agent_config(
    candidate_files: list[dict], 
    system_prompt: str = CHAT_SYSTEM_PROMPT,
    include_reasoning: bool = False
) -> tuple[list[Callable], dict[str, Callable], Any]:
    """
    Build tools, map, and GenerateContentConfig for the RAG agent.
    """
    tools = build_pageindex_tools(candidate_files, include_reasoning=include_reasoning)
    tool_map = {tool.__name__: tool for tool in tools}

    config = types.GenerateContentConfig(
        system_instruction=system_prompt,
        tools=tools,
        temperature=0.0,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )
    return tools, tool_map, config


async def run_pageindex_agent_loop(
    candidate_files: list[dict],
    prompt_contents: Any,
    max_turns: int = None,
    resolve_citations: bool = False,
    citation_link_type: str = "original",
    system_prompt: str = CHAT_SYSTEM_PROMPT,
    include_reasoning: bool = False,
    trace_id: str = "",
) -> dict:
    """
    Run the manual PageIndex agent loop and return a structured result.
    """
    max_turns = max_turns or settings.AGENT_MAX_TURNS
    tools, tool_map, config = get_agent_config(
        candidate_files, 
        system_prompt=system_prompt,
        include_reasoning=include_reasoning
    )

    # Normalise prompt_contents into a list of Content
    if isinstance(prompt_contents, str):
        history = [types.Content(role="user", parts=[types.Part.from_text(text=prompt_contents)])]
    elif isinstance(prompt_contents, types.Content):
        history = [prompt_contents]
    else:
        history = list(prompt_contents)  # already a list of Content

    steps: list[dict] = []
    final_answer = ""
    total_prompt_tokens = 0
    total_candidates_tokens = 0
    turns_completed = 0
    
    logger.info(
        "[RAG][%s][pageindex.agent.start] max_turns=%d candidates=%s",
        trace_id,
        max_turns,
        [file.get("file_id") for file in candidate_files],
    )

    max_turns_reached = False
    for turn_idx in range(max_turns):
        turns_completed = turn_idx + 1
        logger.info("[RAG][%s][pageindex.turn.start] turn=%d", trace_id, turn_idx + 1)
        start_gen = time.perf_counter()
        resp = await async_retry(
            gemini_client.client.aio.models.generate_content,
            model=settings.GEMINI_MODEL,
            contents=history,
            config=config,
            retryable_exceptions=(genai_errors.ServerError,),
        )
        gen_dur = time.perf_counter() - start_gen
        logger.info(
            "[RAG][%s][pageindex.turn.model] turn=%d duration_ms=%d",
            trace_id,
            turn_idx + 1,
            int(gen_dur * 1000),
        )

        if hasattr(resp, "usage_metadata") and resp.usage_metadata:
            total_prompt_tokens += getattr(resp.usage_metadata, 'prompt_token_count', 0) or 0
            total_candidates_tokens += getattr(resp.usage_metadata, 'candidates_token_count', 0) or 0

        if not resp.candidates or not resp.candidates[0].content or not resp.candidates[0].content.parts:
            break

        model_parts = resp.candidates[0].content.parts
        history.append(types.Content(role="model", parts=model_parts))

        tool_calls = []
        turn_text = ""
        for part in model_parts:
            if hasattr(part, "thought") and part.thought:
                steps.append({"type": "thought", "content": str(part.thought)})
            if part.function_call:
                call = part.function_call
                tool_calls.append(call)
                args = dict(call.args)
                reason_val = args.pop("reasoning", None)
                if reason_val:
                    steps.append({"type": "reasoning", "content": reason_val})
                steps.append({"type": "call", "name": call.name, "args": args})
                logger.info(
                    "[RAG][%s][pageindex.tool.call] turn=%d tool=%s args=%s",
                    trace_id,
                    turn_idx + 1,
                    call.name,
                    args,
                )
            if part.text:
                turn_text += part.text

        if not tool_calls:
            logger.info("[RAG][%s][pageindex.answer] turn=%d", trace_id, turn_idx + 1)
            pre_think, parsed_answer = parse_agent_response(turn_text)
            if pre_think:
                steps.append({"type": "conclude", "content": pre_think})
                logger.debug("[RAG][%s][pageindex.answer.reasoning] text=%r", trace_id, pre_think[:300])
            final_answer = parsed_answer
            break

        tool_response_parts = []
        for call in tool_calls:
            try:
                tool_func = tool_map.get(call.name)
                start_tool = time.perf_counter()
                result = (
                    await tool_func(**call.args)
                    if tool_func
                    else f"Error: Tool {call.name} not found."
                )
                tool_dur = time.perf_counter() - start_tool
                logger.info(
                    "[RAG][%s][pageindex.tool.result] turn=%d tool=%s duration_ms=%d result=%s",
                    trace_id,
                    turn_idx + 1,
                    call.name,
                    int(tool_dur * 1000),
                    str(result)[:500],
                )
                steps.append({"type": "tool_output", "name": call.name, "output": str(result)})
                tool_response_parts.append(
                    types.Part.from_function_response(name=call.name, response={"result": result})
                )
            except Exception:
                logger.exception(
                    "[RAG][%s][pageindex.tool.error] turn=%d tool=%s",
                    trace_id,
                    turn_idx + 1,
                    call.name,
                )
                tool_response_parts.append(
                    types.Part.from_function_response(name=call.name, response={"error": str(e)})
                )

        history.append(types.Content(role="user", parts=tool_response_parts))
    else:
        max_turns_reached = True

    sources_data = await build_sources_from_steps(steps, candidate_files)
    final_answer = verify_citations(final_answer, sources_data, resolve_citations, citation_link_type)
    final_answer = sanitize_latex_in_markdown(final_answer)
    logger.info(
        "[RAG][%s][pageindex.complete] turns=%d max_turns=%s sources=%d tokens=%d/%d",
        trace_id,
        turns_completed,
        max_turns_reached,
        len(sources_data),
        total_prompt_tokens,
        total_candidates_tokens,
    )

    return {
        "final_answer": final_answer,
        "max_turns_reached": max_turns_reached,
        "steps": steps,
        "sources": sources_data,
        "tokenUsage": {
            "promptTokens": total_prompt_tokens,
            "completionTokens": total_candidates_tokens,
            "totalTokens": total_prompt_tokens + total_candidates_tokens
        }
    }
