"""Chat Service - Handles Agentic RAG chat operations."""
import json
import re
import logging
import time
from typing import Optional, AsyncGenerator, Any

from google.genai import types

from app.core.config import settings
from app.modules.chat.schemas import ChatHistoryItem, UserContext
from app.modules.chat.history_repository import PERSISTED_STEP_TYPES
from app.modules.metadata.schemas import FaqMetadataSchema
from app.modules.chat.step_formatter import simplify_step
from app.modules.rag.retrieval.service import get_retrieval_service
from app.modules.rag.retrieval.schemas import SourceCitation
from app.modules.rag.retrieval.agent import (
    CHAT_SYSTEM_PROMPT,
    build_pindex_tools,
    build_sources_from_steps,
    run_agent_loop,
    get_agent_config,
    parse_agent_response,
    CitationStreamFormatter,
)
from app.integrations.llm.gemini import gemini_client
from app.modules.faq.service import get_faq_service
from app.modules.chat.analyzer import get_query_analyzer
from app.utils.format_utils import markdown_to_rich_text, sanitize_latex_in_markdown
import asyncio

logger = logging.getLogger(__name__)


class ChatService:
    """Service for Agentic RAG-based chat operations."""

    def __init__(self):
        self._retrieval = get_retrieval_service()
        self._faq_svc = None

    async def _get_faq_svc(self):
        if self._faq_svc is None:
            self._faq_svc = await get_faq_service()
        return self._faq_svc

    async def _embed(self, text: str) -> list[float]:
        return await self._retrieval._qdrant._get_embedding(text)

    async def _prepare_chat_state(
        self,
        question: str,
        user_context: UserContext,
        chat_history: list[ChatHistoryItem],
        metadata_filter: Optional[dict[str, Any]] = None,
    ) -> dict:
        """Retrieve candidate files and build conversation history for the agent."""
        meta_dict = metadata_filter or {}
        candidate_files = await self._retrieval.retrieve_candidate_files(
            query=question,
            metadata_filter=meta_dict,
            user_role=user_context.role,
        )

        if not candidate_files:
            return {"candidate_files": [], "history": []}

        files_info_str = "\n".join([
            f"[{i+1}] ID: {c['file_id']} | Name: {c['file_name']} | Description: {c.get('doc_description', '')}"
            for i, c in enumerate(candidate_files)
        ])
        prompt_text = (
            f"Ngữ cảnh người dùng: {user_context.name} (Vai trò: {user_context.role}, Khóa: {user_context.enrollment_year or 'N/A'})\n\n"
            f"Dưới đây là các tài liệu liên quan được tìm thấy trong cơ sở dữ liệu. Hãy sử dụng công cụ để đọc nội dung chi tiết bằng cách dùng số thứ tự [n] trong ngoặc vuông (ví dụ: '1'):\n{files_info_str}\n\n"
            f"Câu hỏi của người dùng: {question}"
        )

        # Build conversation history (latest 6 turns) + current prompt
        history = []
        for h in chat_history[-6:]:
            role = "user" if h.role == "user" else "model"
            history.append(types.Content(role=role, parts=[types.Part.from_text(text=h.content)]))
        history.append(types.Content(role="user", parts=[types.Part.from_text(text=prompt_text)]))

        return {"candidate_files": candidate_files, "history": history}

    async def generate_chat_response(
        self,
        question: str,
        user_context: UserContext,
        chat_history: list[ChatHistoryItem],
        resolve_citations: bool = False,
        citation_link_type: str = "markdown",
        to_rich_text: bool = False,
    ) -> dict:
        """
        Generate Agentic Chat Response (non-streaming).
        Delegates fully to shared run_agent_loop; returns answer, steps, and sources.
        """
        start_time = time.time()
        pipeline_steps = []
        
        # [1] Analyze query (rewrite + gate + metadata) — 1 LLM call
        analyzer = get_query_analyzer()
        analysis = await analyzer.analyze_query(question, chat_history)
        effective_question = analysis["effective_question"]
        needs_rag = analysis["needs_rag"]
        metadata_filter = analysis.get("metadata_filter") or {}
        
        # Merge user context enrollment_year as fallback if not extracted from query
        if not metadata_filter.get("enrollment_year") and user_context.enrollment_year:
            logger.info("[Chat] Fallback enrollment_year to user context: %s", user_context.enrollment_year)
            metadata_filter["enrollment_year"] = {
                "from_year": user_context.enrollment_year,
                "to_year": user_context.enrollment_year
            }

        logger.info("[Chat] Final metadata_filter applied: %s", metadata_filter or "(none)")

        pipeline_steps.append({
            "type": "query_analysis",
            "original_question": question,
            "effective_question": effective_question,
            "needs_rag": needs_rag,
            "metadata_filter": metadata_filter,
        })

        # [2] Gate = NO: generate direct reply
        if not needs_rag:
            logger.info("[Chat] RAG bypass via gate. Generating direct answer.")
            direct_answer = await analyzer.generate_reply(effective_question, chat_history)
            processing_time_ms = int((time.time() - start_time) * 1000)
            logger.info(f"[Chat] RAG bypass. Final answer for user {user_context.name}: '{direct_answer[:200]}...' (Completed in {processing_time_ms}ms)")
            answer_markdown = direct_answer
            final_answer = answer_markdown
            if to_rich_text:
                final_answer = markdown_to_rich_text(answer_markdown)

            return {
                "answer": final_answer,
                "sources": [],
                "steps": [simplify_step(s) for s in pipeline_steps],
                "token_usage": None,
                "processing_time_ms": processing_time_ms,
            }

        # [3] Embed rewritten question
        question_vector = await self._embed(effective_question)

        # [4] FAQ Pre-check
        faq_svc = await self._get_faq_svc()
        # Omit 'type' filter from FAQ search query filter
        faq_metadata_filter = {k: v for k, v in metadata_filter.items() if k != "type"} if metadata_filter else {}
        faq = await faq_svc.find_best_match(question_vector, faq_metadata_filter)
        if faq:
            pipeline_steps.append({
                "type": "faq_check",
                "hit": True,
                "faq_question": faq.get("question", ""),
            })
            processing_time_ms = int((time.time() - start_time) * 1000)
            logger.info(f"[Chat] FAQ hit: '{faq['question']}' ({processing_time_ms}ms)")
            answer_markdown = faq["answer_markdown"]
            final_answer = answer_markdown
            if to_rich_text:
                final_answer = markdown_to_rich_text(answer_markdown)
            
            return {
                "answer": final_answer,
                "source": "faq",
                "sources": [],
                "steps": [simplify_step(s) for s in pipeline_steps],
                "token_usage": None,
                "processing_time_ms": processing_time_ms,
            }

        pipeline_steps.append({
            "type": "faq_check",
            "hit": False,
        })

        # [5] Prepare Chat State using effective_question
        state = await self._prepare_chat_state(effective_question, user_context, chat_history, metadata_filter)
        candidate_files = state["candidate_files"]

        # Log retrieval step
        retrieval_files_step = [
            {
                "file_id": f.get("file_id"),
                "file_name": f.get("file_name"),
                "doc_score": f.get("doc_score"),
            }
            for f in candidate_files
        ]
        pipeline_steps.append({
            "type": "retrieval",
            "candidate_files": retrieval_files_step,
        })

        if not candidate_files:
            answer_text = "Không tìm thấy tài liệu nào phù hợp với yêu cầu của bạn."
            if to_rich_text:
                answer_text = markdown_to_rich_text(answer_text)
            return {
                "answer": answer_text,
                "sources": [],
                "steps": [simplify_step(s, candidate_files) for s in pipeline_steps],
                "processing_time_ms": int((time.time() - start_time) * 1000),
            }

        result = await run_agent_loop(
            candidate_files=candidate_files,
            prompt_contents=state["history"],
            resolve_citations=resolve_citations,
            citation_link_type=citation_link_type,
        )

        processing_time_ms = int((time.time() - start_time) * 1000)
        logger.info(f"[Chat] Final answer for user {user_context.name}: '{result['final_answer'][:200]}...' (Completed in {processing_time_ms}ms)")

        # Log async interaction
        faq_svc = await self._get_faq_svc()
        asyncio.create_task(faq_svc.log_interaction(
            question=effective_question,
            question_vector=question_vector,
            answer_markdown=result["final_answer"],
            metadata_filter=metadata_filter,
            source_type="chat",
            processing_time_ms=processing_time_ms,
        ))

        answer_markdown = result["final_answer"]
        final_answer = answer_markdown
        if to_rich_text:
            final_answer = markdown_to_rich_text(answer_markdown)

        # Only persist structural pipeline steps — filter out verbose LLM internals
        # (thought, tool_output, reasoning are too large and not useful for history).
        # Whitelist is enforced again at the storage boundary (see ChatHistoryRepository).
        agent_call_steps = [s for s in result["steps"] if s.get("type") in PERSISTED_STEP_TYPES]

        return {
            "answer": final_answer,
            "source": "llm",
            "sources": result["sources"],
            "steps": [simplify_step(s, candidate_files) for s in (pipeline_steps + agent_call_steps)],
            "token_usage": result.get("tokenUsage"),
            "processing_time_ms": processing_time_ms,
        }

    async def stream_chat_response(
        self,
        question: str,
        user_context: UserContext,
        chat_history: list[ChatHistoryItem],
        resolve_citations: bool = False,
        citation_link_type: str = "markdown",
    ) -> AsyncGenerator[str, None]:
        """
        Stream chat response via SSE.

        Maintains its own streaming loop (run_agent_loop cannot stream),
        but uses build_sources_from_steps from agent.py for consistent
        source attribution logic.

        Yields JSON strings:
          - {type: "reasoning", content, done: false}  ← suy luận nội bộ (thought) + kế hoạch Agent
          - {type: "call", name, args, done: false}
          - {type: "text", content, done: false}
          - {done: true, sources: [...], processing_time_ms: ...}
        """
        start_time = time.time()
        pipeline_steps = []
        logger.info(f"[Chat-Stream] Nhận request từ user {user_context.name} (Role: {user_context.role}). Câu hỏi: '{question}'")
        
        # [1] Analyze query (rewrite + gate + metadata) — 1 LLM call
        yield json.dumps({"type": "query_analysis", "content": "Phân tích câu hỏi của người dùng...", "done": False})
        start_analysis = time.perf_counter()
        analyzer = get_query_analyzer()
        analysis = await analyzer.analyze_query(question, chat_history)
        dur_analysis = time.perf_counter() - start_analysis
        
        effective_question = analysis["effective_question"]
        needs_rag = analysis["needs_rag"]
        metadata_filter = analysis.get("metadata_filter") or {}
        
        # Merge user context enrollment_year as fallback if not extracted from query
        if not metadata_filter.get("enrollment_year") and user_context.enrollment_year:
            logger.info("[Chat-Stream] Fallback enrollment_year to user context: %s", user_context.enrollment_year)
            metadata_filter["enrollment_year"] = {
                "from_year": user_context.enrollment_year,
                "to_year": user_context.enrollment_year
            }

        logger.info("[Chat-Stream] Final metadata_filter applied: %s", metadata_filter or "(none)")
        logger.info(f"[Chat-Stream] QueryAnalysis done in {dur_analysis:.2f}s")

        query_analysis_step = {
            "type": "query_analysis",
            "original_question": question,
            "effective_question": effective_question,
            "needs_rag": needs_rag,
            "metadata_filter": metadata_filter,
        }
        pipeline_steps.append(query_analysis_step)
        yield json.dumps({**simplify_step(query_analysis_step), "done": False})

        # [2] Gate = NO: generate direct reply
        if not needs_rag:
            logger.info("[Chat-Stream] RAG bypass via gate. Generating direct answer.")
            start_reply = time.perf_counter()
            direct_answer = await analyzer.generate_reply(effective_question, chat_history)
            dur_reply = time.perf_counter() - start_reply
            yield json.dumps({"type": "text", "content": direct_answer, "done": False})
            processing_time_ms = int((time.time() - start_time) * 1000)
            logger.info(f"[Chat-Stream] Direct reply: {dur_reply:.2f}s. Final answer: '{direct_answer[:150]}...' (Total time: {processing_time_ms / 1000:.2f}s)")
            yield json.dumps({
                "done": True, 
                "sources": [], 
                "steps": [simplify_step(s) for s in pipeline_steps],
                "tokenUsage": None,
                "processingTimeMs": processing_time_ms
            })
            return

        # [3] Embed rewritten question (emit faq_check pending trước để không có khoảng im lặng)
        yield json.dumps({"type": "faq_check", "content": "Tìm kiếm câu hỏi tương tự trong bộ câu hỏi FAQ...", "done": False})
        start_embed = time.perf_counter()
        question_vector = await self._embed(effective_question)
        dur_embed = time.perf_counter() - start_embed
        logger.info(f"[Chat-Stream] Embed done in {dur_embed:.2f}s")

        # [4] FAQ Pre-check
        start_faq = time.perf_counter()
        faq_svc = await self._get_faq_svc()
        # Omit 'type' filter from FAQ search query filter
        faq_metadata_filter = {k: v for k, v in metadata_filter.items() if k != "type"} if metadata_filter else {}
        faq = await faq_svc.find_best_match(question_vector, faq_metadata_filter)
        dur_faq = time.perf_counter() - start_faq
        logger.info(f"[Chat-Stream] FAQ Check done in {dur_faq:.2f}s | hit={faq is not None}")

        if faq:
            faq_check_step = {
                "type": "faq_check",
                "hit": True,
                "faq_question": faq.get("question", ""),
            }
            pipeline_steps.append(faq_check_step)
            yield json.dumps({**simplify_step(faq_check_step), "done": False})

            logger.info("[Chat-Stream] FAQ hit. Sending direct answer.")
            yield json.dumps({"type": "text", "content": faq["answer_markdown"], "done": False})
            processing_time_ms = int((time.time() - start_time) * 1000)
            logger.info(f"[Chat-Stream] FAQ hit for user {user_context.name}: '{faq['question']}' (Completed in {processing_time_ms / 1000:.2f}s)")
            yield json.dumps({
                "done": True, 
                "source": "faq",
                "sources": [], 
                "steps": [simplify_step(s) for s in pipeline_steps],
                "tokenUsage": None,
                "processingTimeMs": processing_time_ms
            })
            return

        faq_check_step = {
            "type": "faq_check",
            "hit": False,
        }
        pipeline_steps.append(faq_check_step)
        yield json.dumps({**simplify_step(faq_check_step), "done": False})

        # [5] Prepare Chat State using effective_question
        yield json.dumps({"type": "retrieval", "content": "Tìm kiếm tài liệu học vụ liên quan...", "done": False})
        start_retrieval = time.perf_counter()
        state = await self._prepare_chat_state(effective_question, user_context, chat_history, metadata_filter)
        candidate_files = state["candidate_files"]
        history = state["history"]
        dur_retrieval = time.perf_counter() - start_retrieval
        logger.info(f"[Chat-Stream] Retrieval done in {dur_retrieval:.2f}s | found={len(candidate_files)} files")

        retrieval_files_step = [
            {
                "file_id": f.get("file_id"),
                "file_name": f.get("file_name"),
                "doc_score": f.get("doc_score"),
            }
            for f in candidate_files
        ]
        retrieval_step = {
            "type": "retrieval",
            "candidate_files": retrieval_files_step,
        }
        pipeline_steps.append(retrieval_step)
        yield json.dumps({**simplify_step(retrieval_step, candidate_files), "done": False})

        if not candidate_files:
            yield json.dumps({"type": "text", "content": "Không tìm thấy tài liệu phù hợp.", "done": False})
            yield json.dumps({
                "done": True, 
                "sources": [], 
                "steps": [simplify_step(s, candidate_files) for s in pipeline_steps], 
                "processingTimeMs": int((time.time() - start_time) * 1000)
            })
            return

        tools, tool_map, config = get_agent_config(candidate_files)

        # Collect get_page_content calls for source attribution at the end
        stream_steps: list[dict] = []
        stream_formatter = None
        current_sources = None
        
        total_prompt_tokens = 0
        total_candidates_tokens = 0
        final_answer_accumulated = ""
        start_agent = time.perf_counter()
        
        logger.info(f"[Chat-Stream] Agent started")

        for turn_idx in range(settings.AGENT_MAX_TURNS):
            start_turn = time.perf_counter()
            tool_calls_in_turn = []
            model_response_parts = []

            turn_text_buffer = ""
            in_answer_block = False
            yielded_text_length = 0
            yielded_reasoning_length = 0

            stream = await gemini_client.client.aio.models.generate_content_stream(
                model=settings.GEMINI_MODEL,
                contents=history,
                config=config,
            )

            turn_prompt_tokens = 0
            turn_candidates_tokens = 0

            async for chunk in stream:
                if hasattr(chunk, "usage_metadata") and chunk.usage_metadata:
                    turn_prompt_tokens = getattr(chunk.usage_metadata, 'prompt_token_count', 0)
                    turn_candidates_tokens = getattr(chunk.usage_metadata, 'candidates_token_count', 0)

                if not chunk.candidates or not chunk.candidates[0].content.parts:
                    continue
                for part in chunk.candidates[0].content.parts:
                    model_response_parts.append(part)

                    # [A] Handle thought part (Gemini Thinking Budget)
                    is_thought_part = hasattr(part, "thought") and part.thought
                    if is_thought_part:
                        if part.text:
                            yield json.dumps({"type": "reasoning", "content": part.text, "done": False})
                        continue

                    # [B] Handle tool/function calls
                    if part.function_call:
                        call = part.function_call
                        tool_calls_in_turn.append(call)
                        stream_steps.append({"type": "call", "name": call.name, "args": dict(call.args)})

                        # Flush any pending reasoning text accumulated before this tool call
                        new_reasoning = turn_text_buffer[yielded_reasoning_length:]
                        if new_reasoning:
                            yield json.dumps({"type": "reasoning", "content": new_reasoning, "done": False})
                            yielded_reasoning_length += len(new_reasoning)

                        # Yield simplified call event
                        call_step = {"type": "call", "name": call.name, "args": dict(call.args)}
                        yield json.dumps({**simplify_step(call_step, candidate_files), "done": False})

                    # [C] Handle non-thought planning/answer text
                    if part.text:
                        turn_text_buffer += part.text
                        if not in_answer_block:
                            match = re.search(r'<answer>', turn_text_buffer, flags=re.IGNORECASE)
                            if match:
                                pre_think = turn_text_buffer[:match.start()]
                                new_reasoning = pre_think[yielded_reasoning_length:]
                                if new_reasoning:
                                    yield json.dumps({"type": "reasoning", "content": new_reasoning, "done": False})
                                    yielded_reasoning_length += len(new_reasoning)
                                in_answer_block = True
                            else:
                                # Progressive stream of reasoning before the answer tag is hit
                                new_reasoning = turn_text_buffer[yielded_reasoning_length:]
                                if new_reasoning:
                                    yield json.dumps({"type": "reasoning", "content": new_reasoning, "done": False})
                                    yielded_reasoning_length += len(new_reasoning)

                        if in_answer_block:
                            if stream_formatter is None:
                                current_sources = await build_sources_from_steps(stream_steps, candidate_files)
                                stream_formatter = CitationStreamFormatter(
                                    current_sources, 
                                    resolve_citations=resolve_citations,
                                    citation_link_type=citation_link_type
                                )

                            match = re.search(r'<answer>\r?\n?(.*)', turn_text_buffer, flags=re.DOTALL | re.IGNORECASE)
                            if match:
                                inside_content = match.group(1)
                                end_match = re.search(r'</answer>', inside_content, flags=re.IGNORECASE)
                                if end_match:
                                    final_to_yield = inside_content[:end_match.start()]
                                    new_text = final_to_yield[yielded_text_length:]
                                    if new_text:
                                        formatted = stream_formatter.process_chunk(new_text)
                                        formatted_flush = stream_formatter.flush()
                                        combined = formatted + formatted_flush
                                        if combined:
                                            final_answer_accumulated += combined
                                            yield json.dumps({"type": "text", "content": combined, "done": False})
                                        yielded_text_length += len(new_text)
                                else:
                                    safe_len = len(inside_content) - 15
                                    if safe_len > yielded_text_length:
                                        new_text = inside_content[yielded_text_length:safe_len]
                                        formatted = stream_formatter.process_chunk(new_text)
                                        if formatted:
                                            final_answer_accumulated += formatted
                                            yield json.dumps({"type": "text", "content": formatted, "done": False})
                                        yielded_text_length += len(new_text)

            # Yield accumulated text based on whether this turn had tool calls
            if tool_calls_in_turn:
                new_reasoning = turn_text_buffer[yielded_reasoning_length:]
                if new_reasoning:
                    yield json.dumps({"type": "reasoning", "content": new_reasoning, "done": False})
                    yielded_reasoning_length += len(new_reasoning)
            else:
                if turn_text_buffer:
                    if in_answer_block:
                        pre_think, final_text = parse_agent_response(turn_text_buffer)
                        if len(final_text) > yielded_text_length:
                            new_text = final_text[yielded_text_length:]
                            if stream_formatter is None:
                                current_sources = await build_sources_from_steps(stream_steps, candidate_files)
                                stream_formatter = CitationStreamFormatter(
                                    current_sources,
                                    resolve_citations=resolve_citations,
                                    citation_link_type=citation_link_type
                                )
                            
                            formatted = stream_formatter.process_chunk(new_text)
                            formatted_flush = stream_formatter.flush()
                            combined = formatted + formatted_flush
                            if combined:
                                final_answer_accumulated += combined
                                yield json.dumps({"type": "text", "content": combined, "done": False})
                        
                        if not final_text and not pre_think and len(turn_text_buffer) > 0 and yielded_text_length == 0:
                            # Fallback IF somehow parse returns empty but we have data
                            if stream_formatter is None:
                                current_sources = await build_sources_from_steps(stream_steps, candidate_files)
                                stream_formatter = CitationStreamFormatter(current_sources)
                                
                            formatted = stream_formatter.process_chunk(turn_text_buffer)
                            formatted_flush = stream_formatter.flush()
                            combined = formatted + formatted_flush
                            if combined:
                                final_answer_accumulated += combined
                                yield json.dumps({"type": "text", "content": combined, "done": False})
                    else:
                        # Turn didn't transition to answer block (e.g. no tags or intermediate turn), flush reasoning
                        new_reasoning = turn_text_buffer[yielded_reasoning_length:]
                        if new_reasoning:
                            yield json.dumps({"type": "reasoning", "content": new_reasoning, "done": False})
                            yielded_reasoning_length += len(new_reasoning)

            # History fragmentation fix: combine text parts into one
            clean_parts = []
            if turn_text_buffer:
                clean_parts.append(types.Part.from_text(text=turn_text_buffer))
            for p in model_response_parts:
                if p.function_call:
                    clean_parts.append(p)
                if hasattr(p, "thought") and p.thought:
                    clean_parts.append(p)
            history.append(types.Content(role="model", parts=clean_parts))
            total_prompt_tokens += turn_prompt_tokens
            total_candidates_tokens += turn_candidates_tokens
            dur_turn = time.perf_counter() - start_turn
            logger.info(f"[Chat-Stream] === Turn {turn_idx + 1} done in {dur_turn:.2f}s | tool_calls={len(tool_calls_in_turn)} | tokens({turn_prompt_tokens}/{turn_candidates_tokens})")

            if not tool_calls_in_turn:
                break

            tool_response_parts = []
            for call in tool_calls_in_turn:
                try:
                    tool_func = tool_map.get(call.name)
                    result = await tool_func(**call.args) if tool_func else f"Error: Tool {call.name} not found."
                    # tool_output not streamed — raw page content is too large and not useful to FE
                    tool_response_parts.append(
                        types.Part.from_function_response(name=call.name, response={"result": result})
                    )
                except Exception as e:
                    logger.error(f"[Chat-Stream] Tool '{call.name}' failed at turn {turn_idx + 1}: {e}", exc_info=True)
                    tool_response_parts.append(
                        types.Part.from_function_response(name=call.name, response={"error": str(e)})
                    )

            history.append(types.Content(role="user", parts=tool_response_parts))

        if current_sources is None:
            current_sources = await build_sources_from_steps(stream_steps, candidate_files)

        dur_agent = time.perf_counter() - start_agent
        if turn_idx == settings.AGENT_MAX_TURNS - 1 and tool_calls_in_turn:
            logger.warning(f"[Chat-Stream] Agent reached max_turns ({settings.AGENT_MAX_TURNS}) and was cut off — possible infinite loop.")
            
        final_answer_accumulated = sanitize_latex_in_markdown(final_answer_accumulated)
        processing_time_ms = int((time.time() - start_time) * 1000)
        logger.info(f"[Chat-Stream] Agent Loop done in {dur_agent:.2f}s | turns={turn_idx + 1} | Usage: {total_prompt_tokens} prompt / {total_candidates_tokens} completion")
        logger.info(f"[Chat-Stream] Done. Total time: {processing_time_ms / 1000:.2f}s. Final answer: '{final_answer_accumulated[:200]}...'")
        
        # Log async interaction
        faq_svc = await self._get_faq_svc()
        asyncio.create_task(faq_svc.log_interaction(
            question=effective_question,
            question_vector=question_vector,
            answer_markdown=final_answer_accumulated,
            metadata_filter=metadata_filter,
            source_type="chat",
            processing_time_ms=processing_time_ms,
        ))
            
        # Only persist structural steps — discard tool_output (contains raw page content).
        # Whitelist is enforced again at the storage boundary (see ChatHistoryRepository).
        filtered_stream_steps = [s for s in stream_steps if s.get("type") in PERSISTED_STEP_TYPES]

        yield json.dumps({
            "done": True,
            "source": "llm",
            "sources": [SourceCitation(**s).model_dump(by_alias=True) for s in current_sources] if current_sources else [],
            "steps": [simplify_step(s, candidate_files) for s in (pipeline_steps + filtered_stream_steps)],
            "tokenUsage": {
                "promptTokens": total_prompt_tokens,
                "completionTokens": total_candidates_tokens,
                "totalTokens": total_prompt_tokens + total_candidates_tokens
            },
            "processingTimeMs": processing_time_ms,
        })


_chat_service_instance: Optional[ChatService] = None


def get_chat_service() -> ChatService:
    global _chat_service_instance
    if _chat_service_instance is None:
        _chat_service_instance = ChatService()
    return _chat_service_instance


chat_service = get_chat_service()
