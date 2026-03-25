"""
Gemini RAG Utils - Helpers for formatting, extracting sources, and injecting citations.
"""
import asyncio
import time
import logging
from typing import Optional, List, Dict, Any, Tuple

from app.repositories.file_repository import FileRepository
from app.storage.r2_client import r2_storage
from app.core.exceptions import GeminiException

logger = logging.getLogger(__name__)

def inject_citations(text: str, response, chunk_map: dict) -> str:
    """Inject citation markers like [^1], [^2] at end of grounded sentences."""
    if not hasattr(response, "candidates") or not response.candidates:
        return text
        
    candidate = response.candidates[0]
    if not hasattr(candidate, "grounding_metadata") or not candidate.grounding_metadata:
        return text
        
    metadata = candidate.grounding_metadata
    if not hasattr(metadata, "grounding_supports") or not metadata.grounding_supports:
        return text
        
    # Group citations by insert index to merge them (e.g. [1, 2])
    insertion_groups = {}
    
    for support in metadata.grounding_supports:
        if not hasattr(support, "segment") or not support.segment:
            continue
        if not hasattr(support, "grounding_chunk_indices") or not support.grounding_chunk_indices:
            continue
            
        end_idx = getattr(support.segment, "end_index", -1)
        if end_idx < 0:
            continue
            
        # Convert abstract chunk indices to user-facing unique source indices
        source_indices = []
        for c_idx in support.grounding_chunk_indices:
            mapped = chunk_map.get(c_idx)
            if mapped:
                source_indices.append(mapped)
                
        if not source_indices:
            continue
            
        # Move index forward to the end of the current sentence or line
        search_idx = end_idx
        while search_idx < len(text) and text[search_idx] not in ['.', '!', '?', '\n']:
            search_idx += 1
            
        if search_idx not in insertion_groups:
            insertion_groups[search_idx] = set()
            
        for s_idx in source_indices:
            insertion_groups[search_idx].add(s_idx)
            
    # Build insertion payloads
    inserts = []
    for idx, s_indices in insertion_groups.items():
        sorted_indices = sorted(list(s_indices))
        # Format as: [^1] [^2] instead of [1] [2]
        citation_str = " " + " ".join([f"[^{i}]" for i in sorted_indices])
        inserts.append((idx, citation_str))
        
    # Sort descending to insert backwards safely
    inserts.sort(key=lambda x: x[0], reverse=True)
    
    result = text
    for index, text_to_insert in inserts:
        if 0 <= index <= len(result):
            result = result[:index] + text_to_insert + result[index:]
            
    return result


def format_chat_history(history: List[Any]) -> str:
    """Format chat history into readable text. Note: history items should have role and content members."""
    if not history:
        return "(Chưa có lịch sử hội thoại)"
    
    formatted = []
    for msg in history:
        role_name = "Sinh viên" if msg.role == "user" else "Trợ lý"
        formatted.append(f"{role_name}: {msg.content}")
    
    return "\n".join(formatted)


def extract_sources(response) -> tuple[Optional[list[dict]], dict]:
    """Extract document sources and return (unique_sources, chunk_to_source_idx_map)."""
    citations = []
    chunk_to_source_map = {}
    
    if not hasattr(response, "candidates") or not response.candidates:
        return None, {}
    
    candidate = response.candidates[0]
    
    if hasattr(candidate, "grounding_metadata") and candidate.grounding_metadata:
        metadata = candidate.grounding_metadata
        
        # Collect actually used chunk indices from grounding_supports
        used_indices = set()
        if hasattr(metadata, "grounding_supports") and metadata.grounding_supports:
            for support in metadata.grounding_supports:
                if hasattr(support, "grounding_chunk_indices"):
                    for idx in support.grounding_chunk_indices:
                        used_indices.add(idx)
        
        # Extract from grounding_chunks (File Search results)
        if hasattr(metadata, "grounding_chunks") and metadata.grounding_chunks:
            for idx, chunk in enumerate(metadata.grounding_chunks):
                if idx not in used_indices:
                    continue
                    
                citation = None
                # Check for retrieved_context (File Search)
                if hasattr(chunk, "retrieved_context") and chunk.retrieved_context:
                    ctx = chunk.retrieved_context
                    citation = {}
                    
                    # Extract title/document name
                    if hasattr(ctx, "title") and ctx.title:
                        citation["title"] = ctx.title
                    
                    # Extract text excerpt
                    if hasattr(ctx, "text") and ctx.text:
                        citation["text"] = ctx.text
                
                # Fallback: Check for web sources
                elif hasattr(chunk, "web") and chunk.web:
                    citation = {}
                    if hasattr(chunk.web, "title"):
                        citation["title"] = chunk.web.title
                
                if citation:
                    citations.append((idx, citation))
    
    # Remove duplicate citations (same title) and build map
    seen = set()
    unique_citations = []
    idx_counter = 1
    
    for orig_idx, citation in citations:
        key = citation.get("title")
        if not key:
            continue
            
        if key not in seen:
            seen.add(key)
            citation["citation_id"] = idx_counter
            unique_citations.append(citation)
            # Map original chunk index to the 1-based index (e.g., [1])
            chunk_to_source_map[orig_idx] = idx_counter
            idx_counter += 1
        else:
            # Find the existing index
            for i, uc in enumerate(unique_citations):
                if uc.get("title") == key:
                    chunk_to_source_map[orig_idx] = i + 1
                    break
    
    return (unique_citations if unique_citations else None), chunk_to_source_map


async def enrich_sources_with_urls(sources: Optional[list[dict]], file_repo: FileRepository) -> Optional[list[dict]]:
    """
    Enrich sources with download URLs by looking up files in database.
    """
    if not sources:
        return sources
    
    # Collect all titles to look up
    titles = [s.get("title") for s in sources if s.get("title")]
    if not titles:
        return sources
    
    # Look up files by display_name
    try:
        files = await file_repo.find_by_display_names(titles)
    except Exception:
        return sources
    
    # Create a map of display_name -> file info
    file_map = {}
    for f in files:
        display_name = f.get("display_name")
        if display_name:
            file_map[display_name] = {
                "file_id": str(f.get("_id")),
                "storage_path": f.get("storage_path"),
            }
    
    # Enrich sources with presigned URLs
    for source in sources:
        title = source.get("title")
        if title and title in file_map:
            file_info = file_map[title]
            path = file_info["storage_path"]
            if path:
                try:
                    source["url"] = await r2_storage.get_file_url(path)
                except Exception:
                    pass
            source["file_id"] = file_info["file_id"]
    
    return sources


def extract_token_usage(response) -> Optional[dict]:
    """Extract token usage statistics from response."""
    usage = None
    
    if hasattr(response, "usage_metadata") and response.usage_metadata:
        usage = response.usage_metadata
    elif hasattr(response, "candidates") and response.candidates:
        c = response.candidates[0]
        if hasattr(c, "usage_metadata") and c.usage_metadata:
            usage = c.usage_metadata
    
    if not usage:
        return None
    
    return {
        "prompt_token_count": getattr(usage, "prompt_token_count", 0),
        "candidates_token_count": getattr(usage, "candidates_token_count", 0),
        "total_token_count": getattr(usage, "total_token_count", 0),
    }


async def wait_for_gemini_operation(client, operation, display_name: str, store_name: str, timeout: int = 120) -> str:
    """Wait for Gemini operation to complete and extract document name."""
    start_time = time.time()
    
    while not operation.done:
        if time.time() - start_time > timeout:
            raise GeminiException(f"Upload timeout after {timeout}s")
        await asyncio.sleep(2)
        operation = await asyncio.to_thread(client.operations.get, operation)
    
    if hasattr(operation, "error") and operation.error:
        raise GeminiException(f"Upload failed: {operation.error}")
    
    # Extract document name
    document_name = (
        getattr(getattr(operation, "result", None), "name", None) or
        getattr(getattr(operation, "response", None), "name", None)
    )
    
    # Fallback: list documents to find by display_name
    if not document_name:
        document_name = await find_gemini_document_by_name(client, store_name, display_name)
    
    if not document_name:
        raise GeminiException("Could not determine document name after upload")
    
    return document_name


async def find_gemini_document_by_name(client, store_name: str, display_name: str) -> Optional[str]:
    """Find document in store by display name."""
    try:
        from app.services.rag.gemini_client import gemini_client
        docs = list(await asyncio.to_thread(
            client.file_search_stores.documents.list,
            parent=store_name
        ))
        for doc in docs:
            if getattr(doc, "display_name", None) == display_name:
                return doc.name
        return docs[-1].name if docs else None
    except Exception as e:
        logger.warning(f"Failed to list Gemini documents: {e}")
        return None
