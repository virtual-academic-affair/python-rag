import logging
import time
from typing import List, Callable, Any
from google.genai import types
from google.genai import errors as genai_errors

from app.core.config import settings
from app.integrations.llm.gemini import gemini_client
from app.utils.format_utils import sanitize_latex_in_markdown
from app.utils.retry import async_retry
from app.modules.rag.query.answering.pageindex.prompts import CHAT_SYSTEM_PROMPT
from app.modules.rag.query.answering.pageindex.tools import build_pindex_tools
from app.modules.rag.query.answering.pageindex.citation import build_sources_from_steps, verify_citations
from app.modules.rag.query.answering.pageindex.parser import parse_agent_response

logger = logging.getLogger(__name__)

def get_agent_config(
    candidate_files: list[dict], 
    system_prompt: str = CHAT_SYSTEM_PROMPT,
    include_reasoning: bool = False
) -> tuple[list[Callable], dict[str, Callable], Any]:
    """
    Build tools, map, and GenerateContentConfig for the RAG agent.
    """
    tools = build_pindex_tools(candidate_files, include_reasoning=include_reasoning)
    tool_map = {tool.__name__: tool for tool in tools}

    config = types.GenerateContentConfig(
        system_instruction=system_prompt,
        tools=tools,
        temperature=0.0,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )
    return tools, tool_map, config


async def run_agent_loop(
    candidate_files: list[dict],
    prompt_contents: Any,
    max_turns: int = None,
    resolve_citations: bool = False,
    citation_link_type: str = "original",
    system_prompt: str = CHAT_SYSTEM_PROMPT,
    include_reasoning: bool = False,
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
    
    logger.info(f"[Agent] Khởi động vòng lặp tự động (Tối đa {max_turns} turns) với {len(candidate_files)} tài liệu ứng viên.")

    max_turns_reached = False
    for turn_idx in range(max_turns):
        logger.info(f"[Agent] Bắt đầu Turn {turn_idx + 1}")
        start_gen = time.perf_counter()
        resp = await async_retry(
            gemini_client.client.aio.models.generate_content,
            model=settings.GEMINI_MODEL,
            contents=history,
            config=config,
            retryable_exceptions=(genai_errors.ServerError,),
        )
        gen_dur = time.perf_counter() - start_gen
        logger.info(f"[Agent] Gemini generation Turn {turn_idx + 1} completed in {gen_dur:.2f}s")

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
                logger.info(f"[Agent] Yêu cầu gọi tool: {call.name} với args: {args}")
            if part.text:
                turn_text += part.text

        if not tool_calls:
            logger.info(f"[Agent] Dừng vòng lặp tại Turn {turn_idx + 1}. Agent đã đưa ra câu trả lời cuối cùng.")
            pre_think, parsed_answer = parse_agent_response(turn_text)
            if pre_think:
                steps.append({"type": "conclude", "content": pre_think})
                logger.info(f"[Agent] Conclude/Pre-answer reasoning: {pre_think[:100]}...")
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
                logger.info(f"[Agent] Tool {call.name} completed in {tool_dur:.2f}s")
                logger.debug(f"[Agent] Kết quả tool {call.name}: {str(result)[:200]}...")
                steps.append({"type": "tool_output", "name": call.name, "output": str(result)})
                tool_response_parts.append(
                    types.Part.from_function_response(name=call.name, response={"result": result})
                )
            except Exception as e:
                logger.error(f"Error executing tool {call.name}: {e}")
                tool_response_parts.append(
                    types.Part.from_function_response(name=call.name, response={"error": str(e)})
                )

        history.append(types.Content(role="user", parts=tool_response_parts))
    else:
        max_turns_reached = True

    sources_data = await build_sources_from_steps(steps, candidate_files)
    final_answer = verify_citations(final_answer, sources_data, resolve_citations, citation_link_type)
    final_answer = sanitize_latex_in_markdown(final_answer)

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
