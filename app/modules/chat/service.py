"""Chat Service - Handles Agentic RAG chat operations."""
import json
import logging
import time
from typing import Optional, AsyncGenerator, Any

from google.genai import types

from app.core.config import settings
from app.modules.chat.schemas import ChatHistoryItem, UserContext
from app.modules.metadata.schemas import FaqMetadataSchema
from app.modules.rag.retrieval.service import get_retrieval_service
from app.modules.rag.retrieval.agent import (
    AGENT_SYSTEM_PROMPT,
    build_pindex_tools,
    build_sources_from_steps,
    run_agent_loop,
    get_agent_config,
    parse_agent_response,
    CitationStreamFormatter,
)
from app.integrations.llm.gemini import gemini_client
from app.modules.faq.service import get_faq_service
from app.modules.metadata.extraction import extract_metadata_from_text
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
        metadata_filter: Optional[FaqMetadataSchema] = None,
    ) -> dict:
        """Retrieve candidate files and build conversation history for the agent."""
        logger.info(f"[Chat] Nhận request chuẩn bị bối cảnh cho user {user_context.name} (Role: {user_context.role}). Câu hỏi: '{question}'")
        meta_dict = metadata_filter.model_dump() if metadata_filter else {}
        candidate_files = await self._retrieval.retrieve_candidate_files(
            query=question,
            metadata_filter=meta_dict,
            user_role=user_context.role,
        )

        if not candidate_files:
            return {"candidate_files": [], "history": []}

        files_info_str = "\n".join([
            f"- ID: {c['file_id']} | Name: {c['file_name']} | Description: {c.get('doc_description', '')}"
            for c in candidate_files
        ])
        prompt_text = (
            f"Ngữ cảnh người dùng: {user_context.name} (Vai trò: {user_context.role}, Khóa: {user_context.enrollment_year or 'N/A'})\n\n"
            f"Dưới đây là các tài liệu liên quan được tìm thấy trong cơ sở dữ liệu. Hãy sử dụng công cụ để đọc nội dung chi tiết nếu cần thiết:\n{files_info_str}\n\n"
            f"Câu hỏi của người dùng: {question}"
        )

        # Build conversation history (latest 6 turns) + current prompt
        history = []
        for h in chat_history[-6:]:
            role = "user" if h.role == "user" else "model"
            history.append(types.Content(role=role, parts=[types.Part.from_text(text=h.content)]))
        history.append(types.Content(role="user", parts=[types.Part.from_text(text=prompt_text)]))

        return {"candidate_files": candidate_files, "history": history}

    async def _evaluate_rag_needs(self, question: str, chat_history: list[ChatHistoryItem]) -> tuple[bool, str, dict]:
        """
        Dùng LLM nhẹ (e.g. Gemini Flash fallback) để quyết định xem câu hỏi có thực sự cần tìm tài liệu quy chế không.
        Trả về (needs_rag, direct_answer, token_usage).
        """
        token_usage = {"prompt_tokens": 0, "candidates_tokens": 0, "total_tokens": 0}
        try:
            logger.info(f"[Chat] Evaluating RAG needs for question: '{question}'")
            
            history_text = "\n".join([f"{'User' if h.role == 'user' else 'Bot'}: {h.content}" for h in chat_history[-3:]])
            
            prompt = types.Content(
                role="user",
                parts=[
                    types.Part.from_text(
                        text=f"""Bạn là trợ lý phân loại ý định người dùng.
Lịch sử chat gần đây:
{history_text}

Câu hỏi hiện tại: "{question}"

Nhiệm vụ: Câu hỏi này có yêu cầu tra cứu tài liệu quy chế, thủ tục, thông báo từ Phòng Giáo vụ không? hay chỉ là giao tiếp thông thường (như "Hi", "Cảm ơn", "Tạm biệt", hoặc câu hỏi ngoài luồng)?
Nếu CÓ cần tra cứu: Trả về duy nhất chữ "YES".
Nếu KHÔNG cần tra cứu: Trả về chữ "NO" kèm theo một câu phản hồi lịch sự, ngắn gọn và giữ vai trò là "Phòng Giáo vụ" (Ví dụ: "NO|Phòng Giáo vụ xin chào. Bạn cần hỗ trợ thông tin gì về quy chế, thủ tục hay học vụ?").

Định dạng trả lời BẮT BUỘC: YES hoặc NO|<câu phản hồi>
""")
                ]
            )

            resp = await gemini_client.client.aio.models.generate_content(
                model=settings.GEMINI_MODEL,
                contents=[prompt],
                config=types.GenerateContentConfig(
                    temperature=0.0
                )
            )

            # Extract token usage
            if resp.usage_metadata:
                token_usage = {
                    "prompt_tokens": resp.usage_metadata.prompt_token_count or 0,
                    "candidates_tokens": resp.usage_metadata.candidates_token_count or 0,
                    "total_tokens": (resp.usage_metadata.prompt_token_count or 0) + (resp.usage_metadata.candidates_token_count or 0)
                }
            
            if resp.candidates and resp.candidates[0].content.parts:
                answer = ""
                for part in resp.candidates[0].content.parts:
                    if not getattr(part, "thought", False):
                        answer = (part.text or "").strip()
                        if answer:
                            break
                            
                if answer.startswith("NO|"):
                    return False, answer.split("NO|", 1)[1].strip(), token_usage
                elif "NO" in answer.upper() and "|" not in answer:
                   return False, "Phòng Giáo vụ sẵn sàng hỗ trợ. Bạn cần tra cứu thông tin gì?", token_usage

            return True, "", token_usage
        except Exception as e:
            logger.error(f"[Chat] RAG Gate Error: {e}")
            return True, "", token_usage # Fail-safe: always use RAG if gate fails

    async def generate_chat_response(
        self,
        question: str,
        user_context: UserContext,
        chat_history: list[ChatHistoryItem],
        metadata_filter: Optional[dict[str, Any]] = None,
    ) -> dict:
        """
        Generate Agentic Chat Response (non-streaming).
        Delegates fully to shared run_agent_loop; returns answer, steps, and sources.
        """
        start_time = time.time()
        
        # [0] Embed question once
        question_vector = await self._embed(question)
        
        # [0.1] Auto-extract metadata if not provided explicitly
        if not metadata_filter:
            metadata_filter = await extract_metadata_from_text(question)
            if metadata_filter:
                logger.info(f"[Chat] Auto-extracted metadata from question: {metadata_filter}")
        
        meta_dict = metadata_filter.model_dump() if hasattr(metadata_filter, "model_dump") else (metadata_filter or {})

        # [1] FAQ Pre-check
        faq_svc = await self._get_faq_svc()
        faq = await faq_svc.find_best_match(question_vector, meta_dict)
        if faq:
            processing_time_ms = int((time.time() - start_time) * 1000)
            logger.info(f"[Chat] FAQ hit: '{faq['question']}' ({processing_time_ms}ms)")
            return {
                "answer": faq["answer_markdown"],
                "source": "faq",
                "sources": [],
                "steps": [],
                "token_usage": None,
                "processing_time_ms": processing_time_ms,
            }

        # [2] Run RAG Gate and State Preparation (Retrieval) in parallel
        # We run them in parallel because most queries require RAG.
        gate_task = self._evaluate_rag_needs(question, chat_history)
        state_task = self._prepare_chat_state(question, user_context, chat_history, metadata_filter)
        
        (needs_rag, direct_answer, gate_usage), state = await asyncio.gather(gate_task, state_task)
        
        if not needs_rag:
            logger.info("[Chat] RAG bypass via gate. Generating direct answer.")
            processing_time_ms = int((time.time() - start_time) * 1000)
            logger.info(f"[Chat] RAG bypass. Final answer for user {user_context.name}: '{direct_answer[:200]}...' (Completed in {processing_time_ms}ms)")
            return {
                "answer": direct_answer,
                "sources": [],
                "steps": [],
                "token_usage": gate_usage,
                "processing_time_ms": processing_time_ms,
            }

        candidate_files = state["candidate_files"]

        if not candidate_files:
            return {
                "answer": "Không tìm thấy tài liệu nào phù hợp với yêu cầu của bạn.",
                "sources": [],
                "steps": [],
                "processing_time_ms": int((time.time() - start_time) * 1000),
            }

        result = await run_agent_loop(
            candidate_files=candidate_files,
            prompt_contents=state["history"],
        )

        processing_time_ms = int((time.time() - start_time) * 1000)
        logger.info(f"[Chat] Final answer for user {user_context.name}: '{result['final_answer'][:200]}...' (Completed in {processing_time_ms}ms)")

        # Log async interaction
        faq_svc = await self._get_faq_svc()
        asyncio.create_task(faq_svc.log_interaction(
            question=question,
            question_vector=question_vector,
            answer_markdown=result["final_answer"],
            metadata_filter=meta_dict,
            source_type="chat",
            processing_time_ms=processing_time_ms,
        ))

        return {
            "answer": result["final_answer"],
            "source": "llm",
            "sources": result["sources"],
            "steps": result["steps"],
            "token_usage": result.get("tokenUsage"),
            "processing_time_ms": processing_time_ms,
        }

    async def stream_chat_response(
        self,
        question: str,
        user_context: UserContext,
        chat_history: list[ChatHistoryItem],
        metadata_filter: Optional[dict[str, Any]] = None,
    ) -> AsyncGenerator[str, None]:
        """
        Stream chat response via SSE.

        Maintains its own streaming loop (run_agent_loop cannot stream),
        but uses build_sources_from_steps from agent.py for consistent
        source attribution logic.

        Yields JSON strings:
          - {type: "thought", content, done: false}
          - {type: "call", name, args, done: false}
          - {type: "tool_output", name, output, done: false}
          - {type: "text", content, done: false}
          - {done: true, sources: [...], processing_time_ms: ...}
        """
        start_time = time.time()
        
        # [0] Embed question once
        question_vector = await self._embed(question)
        
        # [0.1] Auto-extract metadata if not provided explicitly
        if not metadata_filter:
            metadata_filter = await extract_metadata_from_text(question)
            if metadata_filter:
                logger.info(f"[Chat-Stream] Auto-extracted metadata from question: {metadata_filter}")
        
        meta_dict = metadata_filter.model_dump() if hasattr(metadata_filter, "model_dump") else (metadata_filter or {})

        # [1] FAQ Pre-check
        faq_svc = await self._get_faq_svc()
        faq = await faq_svc.find_best_match(question_vector, meta_dict)
        if faq:
            logger.info("[Chat-Stream] FAQ hit. Sending direct answer.")
            yield json.dumps({"type": "text", "content": faq["answer_markdown"], "done": False})
            processing_time_ms = int((time.time() - start_time) * 1000)
            logger.info(f"[Chat-Stream] FAQ hit for user {user_context.name}: '{faq['question']}' (Completed in {processing_time_ms}ms)")
            yield json.dumps({
                "done": True, 
                "source": "faq",
                "sources": [], 
                "tokenUsage": None,
                "processing_time_ms": processing_time_ms
            })
            return

        # [2] Run RAG Gate and State Preparation (Retrieval) in parallel
        gate_task = self._evaluate_rag_needs(question, chat_history)
        state_task = self._prepare_chat_state(question, user_context, chat_history, metadata_filter)
        
        (needs_rag, direct_answer, gate_usage), state = await asyncio.gather(gate_task, state_task)
        
        if not needs_rag:
            logger.info("[Chat-Stream] RAG bypass via gate. Generating direct answer.")
            yield json.dumps({"type": "text", "content": direct_answer, "done": False})
            processing_time_ms = int((time.time() - start_time) * 1000)
            logger.info(f"[Chat-Stream] RAG bypass. Final answer for user {user_context.name}: '{direct_answer[:200]}...' (Completed in {processing_time_ms}ms)")
            yield json.dumps({
                "done": True, 
                "sources": [], 
                "token_usage": gate_usage,
                "processing_time_ms": processing_time_ms
            })
            return

        candidate_files = state["candidate_files"]
        history = state["history"]

        if not candidate_files:
            yield json.dumps({"type": "text", "content": "Không tìm thấy tài liệu phù hợp.", "done": False})
            yield json.dumps({"done": True, "sources": [], "processing_time_ms": int((time.time() - start_time) * 1000)})
            return

        tools, tool_map, config = get_agent_config(candidate_files)

        # Collect get_page_content calls for source attribution at the end
        stream_steps: list[dict] = []
        stream_formatter = None
        current_sources = None
        
        total_prompt_tokens = 0
        total_candidates_tokens = 0
        final_answer_accumulated = ""
        
        logger.info(f"[Chat] Bắt đầu stream response về cho người dùng (Khởi động Agent Stream)")

        for turn_idx in range(settings.AGENT_MAX_TURNS):
            logger.info(f"[Chat-Stream] Vòng lặp stream turn {turn_idx + 1}")
            tool_calls_in_turn = []
            model_response_parts = []

            turn_text_buffer = ""
            in_answer_block = False
            yielded_text_length = 0
            emitted_reasoning = False

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

                    if hasattr(part, "thought") and part.thought:
                        thought_content = str(part.thought)
                        if thought_content != "True":
                            yield json.dumps({"type": "thought", "content": thought_content, "done": False})

                    if part.function_call:
                        call = part.function_call
                        tool_calls_in_turn.append(call)
                        stream_steps.append({"type": "call", "name": call.name, "args": dict(call.args)})
                        logger.info(f"[Chat-Stream] Chuẩn bị gọi tool: {call.name} (args: {call.args})")
                        yield json.dumps({"type": "call", "name": call.name, "args": call.args, "done": False})

                    if part.text:
                        turn_text_buffer += part.text
                        if not tool_calls_in_turn:
                            import re
                            if not in_answer_block:
                                match = re.search(r'<answer>', turn_text_buffer, flags=re.IGNORECASE)
                                if match:
                                    logger.info("[Chat-Stream] Agent bắt đầu stream nội dung <answer> cuối cùng!")
                                    in_answer_block = True
                                    pre_think = turn_text_buffer[:match.start()].strip()
                                    if pre_think and not emitted_reasoning:
                                        yield json.dumps({"type": "reasoning", "content": pre_think, "done": False})
                                        emitted_reasoning = True
                            
                            if in_answer_block:
                                if stream_formatter is None:
                                    current_sources = await build_sources_from_steps(stream_steps, candidate_files)
                                    stream_formatter = CitationStreamFormatter(current_sources)

                                match = re.search(r'<answer>(.*)', turn_text_buffer, flags=re.DOTALL | re.IGNORECASE)
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
                                                yield json.dumps({"type": "text", "content": formatted, "done": False})
                                            yielded_text_length += len(new_text)

            # Yield accumulated text based on whether this turn had tool calls
            if tool_calls_in_turn:
                if turn_text_buffer:
                    yield json.dumps({"type": "reasoning", "content": turn_text_buffer, "done": False})
            else:
                if turn_text_buffer:
                    pre_think, final_text = parse_agent_response(turn_text_buffer)
                    if pre_think and not emitted_reasoning:
                        yield json.dumps({"type": "reasoning", "content": pre_think, "done": False})
                    
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

            if not tool_calls_in_turn:
                break

            tool_response_parts = []
            for call in tool_calls_in_turn:
                try:
                    tool_func = tool_map.get(call.name)
                    result = await tool_func(**call.args) if tool_func else f"Error: Tool {call.name} not found."
                    yield json.dumps({"type": "tool_output", "name": call.name, "output": str(result), "done": False})
                    tool_response_parts.append(
                        types.Part.from_function_response(name=call.name, response={"result": result})
                    )
                except Exception as e:
                    logger.error(f"Error executing tool {call.name}: {e}")
                    tool_response_parts.append(
                        types.Part.from_function_response(name=call.name, response={"error": str(e)})
                    )

            history.append(types.Content(role="user", parts=tool_response_parts))

        if current_sources is None:
            current_sources = await build_sources_from_steps(stream_steps, candidate_files)
            
        processing_time_ms = int((time.time() - start_time) * 1000)
        logger.info(f"[Chat-Stream] Kết thúc stream thành công. Final answer: '{final_answer_accumulated[:200]}...' (Completed in {processing_time_ms}ms). Usage: {total_prompt_tokens} prompt / {total_candidates_tokens} completion")
        
        # Log async interaction
        faq_svc = await self._get_faq_svc()
        asyncio.create_task(faq_svc.log_interaction(
            question=question,
            question_vector=question_vector,
            answer_markdown=final_answer_accumulated,
            metadata_filter=meta_dict,
            source_type="chat",
            processing_time_ms=processing_time_ms,
        ))
            
        yield json.dumps({
            "done": True,
            "source": "llm",
            "sources": current_sources,
            "tokenUsage": {
                "promptTokens": total_prompt_tokens,
                "completionTokens": total_candidates_tokens,
                "totalTokens": total_prompt_tokens + total_candidates_tokens
            },
            "processing_time_ms": processing_time_ms,
        })


_chat_service_instance: Optional[ChatService] = None


def get_chat_service() -> ChatService:
    global _chat_service_instance
    if _chat_service_instance is None:
        _chat_service_instance = ChatService()
    return _chat_service_instance


chat_service = get_chat_service()
