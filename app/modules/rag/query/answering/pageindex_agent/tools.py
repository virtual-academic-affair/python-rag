import logging

from app.integrations.llm.contracts import LLMTool
from app.integrations.pageindex.client import get_page_index_client

logger = logging.getLogger(__name__)

def build_pageindex_tools(candidate_files: list[dict], include_reasoning: bool = False) -> list[LLMTool]:
    """Create bound tool instances so LLM can invoke PageIndex client."""
    client = get_page_index_client()
    allow_ids = [c["file_id"] for c in candidate_files]

    def resolve_file_id(fid: str) -> str:
        """Resolve a file_id which could be a long hex string or a numeric index string like '1'."""
        if not isinstance(fid, str):
            fid = str(fid)
        fid = fid.strip().strip('[]')
        # Try numeric index first
        if fid.isdigit():
            idx = int(fid) - 1
            if 0 <= idx < len(candidate_files):
                return candidate_files[idx]["file_id"]
        return fid

    if include_reasoning:
        async def get_document_structure(file_id: str, reasoning: str) -> str:
            """
            Get the hierarchical table of contents (structure) for a document. 
            Args:
                file_id: The unique identifier of the file/document (or numeric index like '1').
                reasoning: One short Vietnamese sentence explaining why this document structure must be inspected now.
            """
            real_id = resolve_file_id(file_id)
            if real_id not in allow_ids:
                msg = f"Agent requested invalid file_id: {file_id} (Resolved: {real_id}). Allowed IDs: {allow_ids}"
                logger.warning(f"[Agent] {msg}")
                return f'{{"error": "Invalid document reference \'{file_id}\'. Use an [n] index from the supplied candidate list."}}'
            
            file_name = next((c["file_name"] for c in candidate_files if c["file_id"] == real_id), "Unknown")
            logger.info(f"[Agent] Tool call: get_document_structure(file_id='{file_id}', reasoning='{reasoning}') -> Resolved to ID: {real_id} (File: {file_name})")
            return await client.get_document_structure(real_id)

        async def get_page_content(file_id: str, pages: str, reasoning: str) -> str:
            """
            Get the actual text content of specific sections or line ranges.
            Args:
                file_id: The unique identifier of the file/document (or numeric index like '1').
                pages: A string representing line ranges or page numbers (e.g., '10-20', '5,8').
                reasoning: One short Vietnamese sentence explaining why these pages must be read now.
            """
            real_id = resolve_file_id(file_id)
            if real_id not in allow_ids:
                msg = f"Agent requested invalid file_id: {file_id} (Resolved: {real_id}). Allowed IDs: {allow_ids}"
                logger.warning(f"[Agent] {msg}")
                return f'{{"error": "Invalid document reference \'{file_id}\'. Use an [n] index from the supplied candidate list."}}'
            
            file_name = next((c["file_name"] for c in candidate_files if c["file_id"] == real_id), "Unknown")
            logger.info(f"[Agent] Tool call: get_page_content(file_id='{file_id}', pages='{pages}', reasoning='{reasoning}') -> Resolved to ID: {real_id} (File: {file_name})")
            return await client.get_page_content(real_id, pages)

    else:
        async def get_document_structure(file_id: str) -> str:
            """
            Get the hierarchical table of contents (structure) for a document. 
            Args:
                file_id: The unique identifier of the file/document (or numeric index like '1').
            """
            real_id = resolve_file_id(file_id)
            if real_id not in allow_ids:
                msg = f"Agent requested invalid file_id: {file_id} (Resolved: {real_id}). Allowed IDs: {allow_ids}"
                logger.warning(f"[Agent] {msg}")
                return f'{{"error": "Invalid document reference \'{file_id}\'. Use an [n] index from the supplied candidate list."}}'
            
            file_name = next((c["file_name"] for c in candidate_files if c["file_id"] == real_id), "Unknown")
            logger.info(f"[Agent] Tool call: get_document_structure(file_id='{file_id}') -> Resolved to ID: {real_id} (File: {file_name})")
            return await client.get_document_structure(real_id)

        async def get_page_content(file_id: str, pages: str) -> str:
            """
            Get the actual text content of specific sections or line ranges.
            Args:
                file_id: The unique identifier of the file/document (or numeric index like '1').
                pages: A string representing line ranges or page numbers (e.g., '10-20', '5,8').
            """
            real_id = resolve_file_id(file_id)
            if real_id not in allow_ids:
                msg = f"Agent requested invalid file_id: {file_id} (Resolved: {real_id}). Allowed IDs: {allow_ids}"
                logger.warning(f"[Agent] {msg}")
                return f'{{"error": "Invalid document reference \'{file_id}\'. Use an [n] index from the supplied candidate list."}}'
            
            file_name = next((c["file_name"] for c in candidate_files if c["file_id"] == real_id), "Unknown")
            logger.info(f"[Agent] Tool call: get_page_content(file_id='{file_id}', pages='{pages}') -> Resolved to ID: {real_id} (File: {file_name})")
            return await client.get_page_content(real_id, pages)

    reasoning_property = {
        "reasoning": {
            "type": "string",
            "description": "One short Vietnamese sentence explaining why this document content must be read.",
        }
    } if include_reasoning else {}
    reasoning_required = ["reasoning"] if include_reasoning else []

    return [
        LLMTool(
            name="get_document_structure",
            description="Read the hierarchical table-of-contents structure of a candidate document.",
            parameters={
                "type": "object",
                "properties": {
                    "file_id": {
                        "type": "string",
                        "description": "Document ID or candidate index such as '1'.",
                    },
                    **reasoning_property,
                },
                "required": ["file_id", *reasoning_required],
                "additionalProperties": False,
            },
            handler=get_document_structure,
        ),
        LLMTool(
            name="get_page_content",
            description="Read the text content of specified pages or line ranges in a document.",
            parameters={
                "type": "object",
                "properties": {
                    "file_id": {
                        "type": "string",
                        "description": "Document ID or candidate index such as '1'.",
                    },
                    "pages": {
                        "type": "string",
                        "description": "Page or line ranges, for example '10-20' or '5,8'.",
                    },
                    **reasoning_property,
                },
                "required": ["file_id", "pages", *reasoning_required],
                "additionalProperties": False,
            },
            handler=get_page_content,
        ),
    ]
