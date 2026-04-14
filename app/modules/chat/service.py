"""Chat Service - Handles Agentic RAG chat operations."""
import json
import logging
import time
from typing import Optional, AsyncGenerator, Any

from google.genai import types

from app.core.config import settings
from app.modules.chat.schemas import ChatHistoryItem, UserContext
from app.modules.retrieval.service import get_retrieval_service
from app.modules.retrieval.agent import AGENT_SYSTEM_PROMPT, build_pindex_tools
from app.integrations.llm.gemini import gemini_client
from app.integrations.pageindex.client import get_page_index_client

logger = logging.getLogger(__name__)

class ChatService:
    """Service for Agentic RAG-based chat operations."""

    def __init__(self):
        self._retrieval = get_retrieval_service()

    async def _prepare_chat_state(
        self,
        question: str,
        user_context: UserContext,
        chat_history: list[ChatHistoryItem],
        metadata_filter: Optional[dict[str, Any]] = None,
    ) -> dict:
        """Helper to retrieve files and prepare prompt/history for Agentic Chat."""
        # 1. Retrieval
        candidate_files = await self._retrieval.retrieve_candidate_files(
            query=question,
            metadata_filter=metadata_filter,
            user_role=user_context.role
        )

        if not candidate_files:
            return {"candidate_files": [], "candidate_ids": [], "history": [], "prompt": None}

        candidate_ids = [c["file_id"] for c in candidate_files]
        
        # 2. Prepare Context Prompt
        files_info_str = "\n".join([f"- ID: {c['file_id']} | Name: {c['file_name']} | Description: {c.get('doc_description', '')}" for c in candidate_files])
        prompt_text = (
            f"User Context: {user_context.name} (Role: {user_context.role}, Cohort: {user_context.cohort or 'N/A'})\n\n"
            f"Here are the relevant documents found in the database. Use tools to read them:\n{files_info_str}\n\n"
            f"User Question: {question}"
        )

        # 3. Prepare History (Latest 6 turns)
        history = []
        for h in chat_history[-6:]:
            role = "user" if h.role == "user" else "model"
            history.append(types.Content(role=role, parts=[types.Part.from_text(text=h.content)]))
        
        # Add the current prompt as the latest user turn
        history.append(types.Content(role="user", parts=[types.Part.from_text(text=prompt_text)]))

        return {
            "candidate_files": candidate_files,
            "candidate_ids": candidate_ids,
            "history": history,
            "prompt": prompt_text
        }

    async def generate_chat_response(
        self,
        question: str,
        user_context: UserContext,
        chat_history: list[ChatHistoryItem],
        metadata_filter: Optional[dict[str, Any]] = None,
    ) -> dict:
        """Generate Agentic Chat Response with captured reasoning steps."""
        start_time = time.time()
        
        # 1. Preparation
        state = await self._prepare_chat_state(question, user_context, chat_history, metadata_filter)
        candidate_files = state["candidate_files"]
        candidate_ids = state["candidate_ids"]
        history = state["history"]

        if not candidate_files:
            return {
                "answer": "Không tìm thấy tài liệu nào phù hợp với yêu cầu của bạn.",
                "sources": [],
                "steps": [],
                "processing_time_ms": int((time.time() - start_time) * 1000)
            }

        # 2. Manual Agent Loop
        tools = build_pindex_tools(candidate_ids)
        tool_map = {tool.__name__: tool for tool in tools}
        
        config = types.GenerateContentConfig(
            system_instruction=AGENT_SYSTEM_PROMPT,
            tools=tools,
            temperature=0.0,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True)
        )

        steps = []
        max_turns = 5
        turn_count = 0
        final_answer = ""
        
        while turn_count < max_turns:
            turn_count += 1
            
            resp = await gemini_client.client.aio.models.generate_content(
                model=settings.GEMINI_MODEL,
                contents=history,
                config=config
            )
            
            if not resp.candidates or not resp.candidates[0].content.parts:
                break
                
            model_parts = resp.candidates[0].content.parts
            history.append(types.Content(role="model", parts=model_parts))
            
            tool_calls = []
            for part in model_parts:
                if part.thought:
                    steps.append({"type": "thought", "content": str(part.thought)})
                if part.function_call:
                    call = part.function_call
                    tool_calls.append(call)
                    steps.append({"type": "call", "name": call.name, "args": call.args})
                if part.text:
                    final_answer += part.text

            if not tool_calls:
                break
                
            # Execute tools
            tool_response_parts = []
            for call in tool_calls:
                try:
                    tool_func = tool_map.get(call.name)
                    if tool_func:
                        result = await tool_func(**call.args)
                        steps.append({"type": "tool_output", "name": call.name, "output": result})
                        tool_response_parts.append(types.Part.from_function_response(
                            name=call.name,
                            response={"result": result}
                        ))
                except Exception as e:
                    logger.error(f"Error executing tool {call.name}: {e}")
                    tool_response_parts.append(types.Part.from_function_response(
                        name=call.name,
                        response={"error": str(e)}
                    ))
            
            history.append(types.Content(role="user", parts=tool_response_parts))

        # 3. Format sources
        formatted_sources = []
        for i, c in enumerate(candidate_files):
            formatted_sources.append({
                "citation_id": i + 1,
                "title": c.get("file_name", ""),
                "file_id": c.get("file_id"),
                "text": c.get("doc_description", "")
            })

        return {
            "answer": final_answer,
            "sources": formatted_sources,
            "steps": steps,
            "processing_time_ms": int((time.time() - start_time) * 1000),
        }

    async def stream_chat_response(
        self,
        question: str,
        user_context: UserContext,
        chat_history: list[ChatHistoryItem],
        metadata_filter: Optional[dict[str, Any]] = None,
    ) -> AsyncGenerator[str, None]:
        """Stream chat response using google-genai tools stream."""
        start_time = time.time()
        
        # 1. Preparation
        state = await self._prepare_chat_state(question, user_context, chat_history, metadata_filter)
        candidate_files = state["candidate_files"]
        candidate_ids = state["candidate_ids"]
        history = state["history"]

        if not candidate_files:
            yield json.dumps({"type": "text", "content": "Không tìm thấy tài liệu phù hợp.", "done": False})
            yield json.dumps({"done": True, "sources": [], "processing_time_ms": int((time.time() - start_time) * 1000)})
            return

        # 2. Prepare Tools and Config for Manual Loop
        tools = build_pindex_tools(candidate_ids)
        tool_map = {tool.__name__: tool for tool in tools}
        
        config = types.GenerateContentConfig(
            system_instruction=AGENT_SYSTEM_PROMPT,
            tools=tools,
            temperature=0.0,
            # We manage turns manually to yield tool calls to the frontend
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True)
        )

        max_turns = 5
        turn_count = 0
        
        while turn_count < max_turns:
            turn_count += 1
            tool_calls_in_turn = []
            model_response_parts = []
            
            # Request stream for current turn
            stream = await gemini_client.client.aio.models.generate_content_stream(
                model=settings.GEMINI_MODEL,
                contents=history,
                config=config
            )
            
            async for chunk in stream:
                if not chunk.candidates or not chunk.candidates[0].content.parts:
                    continue
                    
                for part in chunk.candidates[0].content.parts:
                    model_response_parts.append(part)
                    
                    # A. Yield Thoughts
                    if hasattr(part, 'thought') and part.thought:
                        thought_content = str(part.thought)
                        if thought_content != "True":
                            yield json.dumps({"type": "thought", "content": thought_content, "done": False})
                    
                    # B. Yield Tool Calls & Collect for Execution
                    if part.function_call:
                        call = part.function_call
                        tool_calls_in_turn.append(call)
                        yield json.dumps({
                            "type": "call", 
                            "name": call.name, 
                            "args": call.args,
                            "done": False
                        })
                    
                    # C. Yield Text
                    if part.text:
                        yield json.dumps({"type": "text", "content": part.text, "done": False})

            # Add model's turn to history
            history.append(types.Content(role="model", parts=model_response_parts))

            # If no tool calls, the conversation turn is finished
            if not tool_calls_in_turn:
                break
                
            # Execute tools and prepare response parts
            tool_response_parts = []
            for call in tool_calls_in_turn:
                try:
                    tool_func = tool_map.get(call.name)
                    if not tool_func:
                        result = f"Error: Tool {call.name} not found."
                    else:
                        # Execute the tool (all tools in build_tools are async)
                        result = await tool_func(**call.args)
                    
                    # Yield tool output to frontend for transparency
                    yield json.dumps({
                        "type": "tool_output",
                        "name": call.name,
                        "output": str(result),
                        "done": False
                    })
                    
                    tool_response_parts.append(types.Part.from_function_response(
                        name=call.name,
                        response={"result": result}
                    ))
                except Exception as e:
                    logger.error(f"Error executing tool {call.name}: {e}")
                    tool_response_parts.append(types.Part.from_function_response(
                        name=call.name,
                        response={"error": str(e)}
                    ))

            # Add tool results to history as a user/tool role
            history.append(types.Content(role="user", parts=tool_response_parts))

        # Final meta-chunk with sources
        formatted_sources = []
        for i, c in enumerate(candidate_files):
            formatted_sources.append({
                "citation_id": i + 1,
                "title": c.get("file_name", ""),
                "file_id": c.get("file_id"),
                "text": c.get("doc_description", "")
            })

        yield json.dumps({
            "done": True,
            "sources": formatted_sources,
            "processing_time_ms": int((time.time() - start_time) * 1000)
        })

_chat_service_instance: Optional[ChatService] = None

def get_chat_service() -> ChatService:
    global _chat_service_instance
    if _chat_service_instance is None:
        _chat_service_instance = ChatService()
    return _chat_service_instance

chat_service = get_chat_service()
