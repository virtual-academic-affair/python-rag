"""Chat Service - Handles Agentic RAG chat operations."""
import json
import logging
import time
from typing import Optional, AsyncGenerator, Any

from google.genai import types

from app.core.config import settings
from app.modules.chat.schemas import ChatHistoryItem, UserContext
from app.modules.retrieval.service import get_retrieval_service
from app.integrations.llm.gemini import gemini_client
from app.integrations.pageindex.client import get_page_index_client

logger = logging.getLogger(__name__)

AGENT_SYSTEM_PROMPT = """
You are an intelligent educational assistant.
You are equipped with tools to read documents using a hierarchical structure index.
You will be provided a list of relevant document IDs for the user's question.

TOOL USE WORKFLOW:
1. Use `get_document_structure(doc_id)` to view the table of contents and locate relevant sections. The structure contains `line_num` for each section.
2. Use `get_page_content(doc_id, pages="start_line-end_line")` to extract the actual text from those sections. Never guess the text! Always fetch it. 
3. If the fetched text is insufficient, fetch another section or document.
4. Formulate your final answer in simple language based on the text.

RULES:
- Do not expose `doc_id` or tool details in your final answer.
- Answer solely based on the documents. If not found, say you don't know.
- Cite the file names (which are provided) instead of doc_ids when referring to sources.
"""

class ChatService:
    """Service for Agentic RAG-based chat operations."""

    def __init__(self):
        self._retrieval = get_retrieval_service()

    def _build_tools(self, available_doc_ids: list[str]):
        """Create bound tool instances so LLM can invoke PageIndex client."""
        client = get_page_index_client()

        async def get_document(doc_id: str) -> str:
            """
            Get metadata for a document including its name, description, and status.
            
            Args:
                doc_id: The unique identifier of the document.
            """
            if doc_id not in available_doc_ids:
                return '{"error": "Access denied or document not found."}'
            return await client.get_document(doc_id)

        async def get_document_structure(doc_id: str) -> str:
            """
            Get the hierarchical table of contents (structure) for a document. 
            Use this to find relevant sections and their line numbers.
            
            Args:
                doc_id: The unique identifier of the document.
            """
            if doc_id not in available_doc_ids:
                return '{"error": "Access denied or document not found."}'
            return await client.get_document_structure(doc_id)

        async def get_page_content(doc_id: str, pages: str) -> str:
            """
            Get the actual text content of specific sections or line ranges.
            
            Args:
                doc_id: The unique identifier of the document.
                pages: A string representing line ranges or page numbers (e.g., '10-20', '5,8').
            """
            if doc_id not in available_doc_ids:
                return '{"error": "Access denied or document not found."}'
            return await client.get_page_content(doc_id, pages)

        return [get_document, get_document_structure, get_page_content]

    async def generate_chat_response(
        self,
        question: str,
        user_context: UserContext,
        chat_history: list[ChatHistoryItem],
        metadata_filter: Optional[dict[str, Any]] = None,
    ) -> dict:
        """Generate Agentic Chat Response natively with google-genai."""
        start_time = time.time()
        
        # 1. Vector Search for Candidates
        candidate_files = await self._retrieval.retrieve_candidate_files(
            query=question,
            metadata_filter=metadata_filter,
            user_role=user_context.role
        )

        candidate_ids = [c["file_id"] for c in candidate_files]
        sources = candidate_files  # The final sources can be refined if we track tool calls
        
        # 2. Prepare Context Prompt
        files_info_str = "\n".join([f"- ID: {c['file_id']} | Name: {c['file_name']} | Description: {c.get('doc_description', '')}" for c in candidate_files])
        prompt = (
            f"User Context: {user_context.name} (Role: {user_context.role}, Cohort: {user_context.cohort})\n\n"
            f"Here are the relevant documents found in the database. Use tools to read them:\n{files_info_str}\n\n"
            f"User Question: {question}"
        )

        if not candidate_files:
            return {
                "answer": "Không tìm thấy tài liệu nào phù hợp với yêu cầu của bạn.",
                "sources": [],
                "processing_time_ms": int((time.time() - start_time) * 1000)
            }

        # 3. Prepare History
        history_contents = []
        for h in chat_history[-6:]:
            role = "user" if h.role == "user" else "model"
            history_contents.append(types.Content(role=role, parts=[types.Part.from_text(text=h.content)]))

        # 4. Create Chat Session and Send
        config = types.GenerateContentConfig(
            system_instruction=AGENT_SYSTEM_PROMPT,
            tools=self._build_tools(candidate_ids),
            temperature=0.0
        )
        
        chat = gemini_client.client.aio.chats.create(
            model=settings.GEMINI_MODEL,
            history=history_contents,
            config=config
        )
        
        resp = await chat.send_message(prompt)

        # Format sources for schema
        formatted_sources = []
        for i, c in enumerate(candidate_files):
            formatted_sources.append({
                "citation_id": i + 1,
                "title": c.get("file_name", ""),
                "file_id": c.get("file_id"),
                "text": c.get("doc_description", "")
            })

        return {
            "answer": resp.text or "",
            "sources": formatted_sources,
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
        
        candidate_files = await self._retrieval.retrieve_candidate_files(
            query=question,
            metadata_filter=metadata_filter,
            user_role=user_context.role
        )

        candidate_ids = [c["file_id"] for c in candidate_files]
        
        if not candidate_files:
            yield json.dumps({"chunk": "Không tìm thấy tài liệu nào phù hợp.", "done": False})
            yield json.dumps({"done": True, "sources": [], "processing_time_ms": int((time.time() - start_time) * 1000)})
            return

        files_info_str = "\n".join([f"- ID: {c['file_id']} | Name: {c['file_name']} | Description: {c.get('doc_description', '')}" for c in candidate_files])
        prompt = (
            f"User Context: {user_context.name} (Role: {user_context.role})\n"
            f"Available Documents:\n{files_info_str}\n\n"
            f"User Question: {question}"
        )

        history_contents = []
        for h in chat_history[-6:]:
            role = "user" if h.role == "user" else "model"
            history_contents.append(types.Content(role=role, parts=[types.Part.from_text(text=h.content)]))

        # 1. Prepare Tools Map
        tools_list = self._build_tools(candidate_ids)
        tool_map = {tool.__name__: tool for tool in tools_list}
        
        # 2. Prepare History for Manual Loop
        # We start with existing chat history + system instruction
        history = history_contents.copy()
        history.append(types.Content(role="user", parts=[types.Part.from_text(text=prompt)]))
        
        config = types.GenerateContentConfig(
            system_instruction=AGENT_SYSTEM_PROMPT,
            tools=tools_list,
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
