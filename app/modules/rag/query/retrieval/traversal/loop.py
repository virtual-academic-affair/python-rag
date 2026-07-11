from __future__ import annotations
import logging
import time
from google.genai import types
from google.genai import errors as genai_errors

from app.core.exceptions import CorpusTraversalError
from app.core.config import settings
from app.integrations.llm.gemini import gemini_client
from app.utils.retry import async_retry
from app.modules.corpus.repositories.corpus_node_repository import CorpusNodeRepository
from app.modules.rag.query.retrieval.traversal.prompts import CORPUS_TRAVERSAL_PROMPT
from app.modules.rag.query.retrieval.traversal.tools import build_traversal_tools

logger = logging.getLogger(__name__)


def _upstream_status_code(exc: Exception) -> int:
    status_code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    return status_code if isinstance(status_code, int) and status_code in (429, 503) else 502


async def run_corpus_traversal(
    question: str,
    repo: CorpusNodeRepository,
    allowed_files: set[str],
    allowed_faqs: set[str],
    max_turns: int = 10,
) -> tuple[list[str], list[str]]:
    """
    Run an LLM agent that navigates the topic tree using tools to select relevant topics.
    Returns:
        Tuple of selected topic keys and expansion stack.
    """
    tools = build_traversal_tools(repo, allowed_files, allowed_faqs)
    tool_map = {tool.__name__: tool for tool in tools}

    config = types.GenerateContentConfig(
        system_instruction=CORPUS_TRAVERSAL_PROMPT,
        tools=tools,
        temperature=0.0,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )

    history = [
        types.Content(
            role="user",
            parts=[types.Part.from_text(text=f'Hãy tìm tài liệu liên quan đến câu hỏi: "{question}"')]
        )
    ]

    selected_keys: list[str] = []
    expand_stack: list[str] = []
    logger.info(f"[Traversal Agent] Starting corpus traversal agent loop (max turns: {max_turns})")

    for turn_idx in range(max_turns):
        logger.info(f"[Traversal Agent] Start Turn {turn_idx + 1}")
        start_gen = time.perf_counter()
        
        # Use corpus specific model if configured, else default gemini model
        model = settings.CORPUS_TOPIC_MODEL or settings.GEMINI_MODEL
        
        try:
            resp = await async_retry(
                gemini_client.client.aio.models.generate_content,
                model=model,
                contents=history,
                config=config,
                retryable_exceptions=(genai_errors.ServerError,),
            )
        except Exception as e:
            logger.error("[Traversal Agent] Gemini generation failed: %s", e, exc_info=True)
            raise CorpusTraversalError(
                f"Corpus traversal LLM call failed: {e}",
                status_code=_upstream_status_code(e),
            ) from e
        gen_dur = time.perf_counter() - start_gen
        logger.info(f"[Traversal Agent] Turn {turn_idx + 1} generation completed in {gen_dur:.2f}s")

        if not resp.candidates or not resp.candidates[0].content or not resp.candidates[0].content.parts:
            logger.warning("[Traversal Agent] Model returned empty content. Stopping.")
            break

        model_parts = resp.candidates[0].content.parts
        history.append(types.Content(role="model", parts=model_parts))

        tool_calls = []
        for part in model_parts:
            if part.function_call:
                tool_calls.append(part.function_call)

        if not tool_calls:
            logger.info("[Traversal Agent] Model did not call any tools. Stopping.")
            break

        tool_response_parts = []
        should_stop = False

        for call in tool_calls:
            logger.info(f"[Traversal Agent] Tool Call: {call.name} with args: {call.args}")
            # Execute traversal tools, including select_topics, so final selection is validated.
            try:
                tool_func = tool_map.get(call.name)
                if tool_func:
                    result = await tool_func(**call.args)
                else:
                    result = f"Error: Tool {call.name} not found."
                if call.name == "select_topics":
                    if isinstance(result, dict):
                        selected_keys = list(result.get("selected") or [])
                        expand_stack = list(result.get("expand_stack") or [])
                    else:
                        selected_keys = []
                        expand_stack = []
                    logger.info(
                        "[Traversal Agent] select_topics validated. Selected: %s. Exiting loop.",
                        selected_keys,
                    )
                    should_stop = True
                
                tool_response_parts.append(
                    types.Part.from_function_response(
                        name=call.name,
                        response={"result": result}
                    )
                )
            except Exception as e:
                logger.error(f"[Traversal Agent] Error calling tool {call.name}: {e}", exc_info=True)
                tool_response_parts.append(
                    types.Part.from_function_response(
                        name=call.name,
                        response={"error": str(e)}
                    )
                )

        history.append(types.Content(role="user", parts=tool_response_parts))
        if should_stop:
            break
    else:
        logger.warning("[Traversal Agent] Max turns reached without explicit topic selection.")

    return selected_keys, expand_stack
