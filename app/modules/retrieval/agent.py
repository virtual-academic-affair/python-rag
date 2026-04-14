"""
Shared RAG Agent logic: Prompt and Tools for Gemini GenAI.
Used by both Chat and Email Inquiry services.
"""
from typing import List, Callable, Dict, Any, Awaitable
from app.integrations.pageindex.client import get_page_index_client

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

def build_pindex_tools(allow_ids: List[str]) -> List[Callable]:
    """Create bound tool instances so LLM can invoke PageIndex client."""
    client = get_page_index_client()

    async def get_document_structure(doc_id: str) -> str:
        """
        Get the hierarchical table of contents (structure) for a document. 
        Args:
            doc_id: The unique identifier of the document.
        """
        if doc_id not in allow_ids:
            return '{"error": "Access denied or document not found."}'
        return await client.get_document_structure(doc_id)

    async def get_page_content(doc_id: str, pages: str) -> str:
        """
        Get the actual text content of specific sections or line ranges.
        Args:
            doc_id: The unique identifier of the document.
            pages: A string representing line ranges or page numbers (e.g., '10-20', '5,8').
        """
        if doc_id not in allow_ids:
            return '{"error": "Access denied or document not found."}'
        return await client.get_page_content(doc_id, pages)

    return [get_document_structure, get_page_content]
