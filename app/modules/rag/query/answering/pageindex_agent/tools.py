import logging
from typing import List, Callable
from app.integrations.pageindex.client import get_page_index_client

logger = logging.getLogger(__name__)

def build_pageindex_tools(candidate_files: List[dict], include_reasoning: bool = False) -> List[Callable]:
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
                reasoning: Brief explanation in Vietnamese (a few sentences) of why you need to inspect this document's structure now.
            """
            real_id = resolve_file_id(file_id)
            if real_id not in allow_ids:
                msg = f"Agent requested invalid file_id: {file_id} (Resolved: {real_id}). Allowed IDs: {allow_ids}"
                logger.warning(f"[Agent] {msg}")
                return f'{{"error": "Tài liệu \'{file_id}\' không hợp lệ. Hãy dùng số thứ tự [n] trong danh sách được cung cấp."}}'
            
            file_name = next((c["file_name"] for c in candidate_files if c["file_id"] == real_id), "Unknown")
            logger.info(f"[Agent] Tool call: get_document_structure(file_id='{file_id}', reasoning='{reasoning}') -> Resolved to ID: {real_id} (File: {file_name})")
            return await client.get_document_structure(real_id)

        async def get_page_content(file_id: str, pages: str, reasoning: str) -> str:
            """
            Get the actual text content of specific sections or line ranges.
            Args:
                file_id: The unique identifier of the file/document (or numeric index like '1').
                pages: A string representing line ranges or page numbers (e.g., '10-20', '5,8').
                reasoning: Brief explanation in Vietnamese (a few sentences) of why you need to read these pages now.
            """
            real_id = resolve_file_id(file_id)
            if real_id not in allow_ids:
                msg = f"Agent requested invalid file_id: {file_id} (Resolved: {real_id}). Allowed IDs: {allow_ids}"
                logger.warning(f"[Agent] {msg}")
                return f'{{"error": "Tài liệu \'{file_id}\' không hợp lệ. Hãy dùng số thứ tự [n] trong danh sách được cung cấp."}}'
            
            file_name = next((c["file_name"] for c in candidate_files if c["file_id"] == real_id), "Unknown")
            logger.info(f"[Agent] Tool call: get_page_content(file_id='{file_id}', pages='{pages}', reasoning='{reasoning}') -> Resolved to ID: {real_id} (File: {file_name})")
            return await client.get_page_content(real_id, pages)

        return [get_document_structure, get_page_content]
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
                return f'{{"error": "Tài liệu \'{file_id}\' không hợp lệ. Hãy dùng số thứ tự [n] trong danh sách được cung cấp."}}'
            
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
                return f'{{"error": "Tài liệu \'{file_id}\' không hợp lệ. Hãy dùng số thứ tự [n] trong danh sách được cung cấp."}}'
            
            file_name = next((c["file_name"] for c in candidate_files if c["file_id"] == real_id), "Unknown")
            logger.info(f"[Agent] Tool call: get_page_content(file_id='{file_id}', pages='{pages}') -> Resolved to ID: {real_id} (File: {file_name})")
            return await client.get_page_content(real_id, pages)

        return [get_document_structure, get_page_content]
