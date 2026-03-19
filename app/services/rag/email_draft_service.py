"""
Email Draft Service - Pure function for generating email replies.
Called internally by orchestrator when email is classified as 'inquiry'.
"""

import asyncio
import logging
from typing import Dict, Any, Optional, List

from google.genai import types

from app.core.config import settings
from app.core.prompts import EMAIL_DRAFT_REPLY_PROMPT
from app.models.schemas import InquiryIntent, InquiryTypesResult
from app.repositories.file_repository import FileRepository
from app.services.rag.gemini_client import gemini_client
from app.services.rag.utils.gemini_rag_utils import (
    extract_sources,
    inject_citations,
    enrich_sources_with_urls,
    extract_token_usage
)
from app.services.rag.utils.store_utils import resolve_store
from app.services.rag.utils.filter_builder import convert_metadata_filter_to_gemini_format

logger = logging.getLogger(__name__)


async def draft_email_reply(
    original_subject: str,
    original_body: str,
    additional_context: Optional[str] = None,
    store_name: Optional[str] = None,
    metadata_filter: Optional[str] = None,
) -> dict:
    """
    Draft a professional email reply using RAG.
    """
    if not store_name:
        raise ValueError("store_name is required. RAG Service requires File Search for email replies.")
    
    prompt_parts = [
        EMAIL_DRAFT_REPLY_PROMPT,
        f"\n**EMAIL GỐC:**",
        f"Subject: {original_subject}",
        f"Body:\n{original_body}",
    ]
    
    if additional_context:
        prompt_parts.append(f"\n**Chỉ dẫn thêm:** {additional_context}")
    
    full_prompt = "\n".join(prompt_parts)
    
    config = types.GenerateContentConfig(
        temperature=0.7,
        max_output_tokens=1500,
        response_mime_type="text/plain",
    )
    
    # Add File Search tool
    if metadata_filter:
        file_search_config = types.FileSearch(
            fileSearchStoreNames=[store_name],
            metadataFilter=metadata_filter
        )
    else:
        file_search_config = types.FileSearch(
            fileSearchStoreNames=[store_name]
        )
    
    config.tools = [
        types.Tool(fileSearch=file_search_config)
    ]
    
    response = await asyncio.to_thread(
        gemini_client.client.models.generate_content,
        model=settings.GEMINI_MODEL,
        contents=full_prompt,
        config=config,
    )
    
    answer = response.text or ""
    
    sources, chunk_map = extract_sources(response)
    sources = sources or []
    
    if answer and chunk_map:
        answer = inject_citations(answer, response, chunk_map)
    
    # Needs FileRepository for enrich
    file_repo = FileRepository()
    sources = await enrich_sources_with_urls(sources, file_repo) or []
    
    return {
        "answer": answer,
        "sources": sources,
        "token_usage": extract_token_usage(response),
    }


async def extract_inquiry_intent(subject: str, body: str) -> Optional[str]:
    """
    Extract the main inquiry intent or question from the email.
    """
    prompt = (
        "Trích xuất câu hỏi chính hoặc ý định của người dùng từ email dưới đây.\n"
        "Đảm bảo câu hỏi hoặc ý định được trích xuất bằng tiếng Việt.\n\n"
        f"Tiêu đề: {subject}\n"
        f"Nội dung:\n{body}"
    )
    
    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=InquiryIntent,
        temperature=0.0,
    )
    
    try:
        response = await asyncio.to_thread(
            gemini_client.client.models.generate_content,
            model=settings.GEMINI_MODEL,  # using default model
            contents=prompt,
            config=config,
        )
        
        if response.text:
            import json
            data = json.loads(response.text)
            return data.get("question")
        return None
    except Exception as e:
        logger.error(f"Failed to extract intent: {e}")
        return None


async def extract_inquiry_types(subject: str, body: str) -> Optional[List[str]]:
    """
    Extract the inquiry types categories from the email content.
    """
    prompt = (
        "Phân loại email hỏi đáp dưới đây thành các mảng/loại thắc mắc.\n"
        "Bạn CHỈ ĐƯỢC PHÉP CHỌN các giá trị sau đây (viết thường tiếng Anh):\n"
        "- 'graduation': Các thắc mắc liên quan đến tốt nghiệp, xét tốt nghiệp.\n"
        "- 'training': Các thắc mắc chung về quá trình đào tạo, học tập, học vụ.\n"
        "- 'procedure': Các thắc mắc liên quan đến quy trình, thủ tục, đơn từ hành chính.\n"
        "Nghiêm cấm chọn bất kỳ từ khóa nào khác ngoại trừ 3 từ khóa trên. Nếu không rõ ràng, hãy chọn 'training'.\n"
        "Hãy tuân thủ đúng định dạng JSON object được yêu cầu.\n\n"
        f"Tiêu đề: {subject}\n"
        f"Nội dung:\n{body}"
    )
    
    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=InquiryTypesResult,
        temperature=0.0,
    )
    
    try:
        response = await asyncio.to_thread(
            gemini_client.client.models.generate_content,
            model=settings.GEMINI_MODEL,
            contents=prompt,
            config=config,
        )
        
        if response.text:
            import json
            text = response.text.strip()
            # Handle markdown json blocks just in case
            if text.startswith("```"):
                text = "\n".join(text.split("\n")[1:-1])
            data = json.loads(text)
            
            if isinstance(data, list):
                return data
                
            return data.get("inquiryTypes", data.get("inquiry_types", []))
        return []
    except Exception as e:
        logger.error(f"Failed to extract inquiry types: {e}")
        return []


async def draft_inquiry_email_reply(
    subject: str,
    body: str,
    additional_context: Optional[str] = None,
    store_id: Optional[str] = None,
    metadata_filter: Optional[Dict[str, Any]] = None,
    extracted_question: Optional[str] = None,
    inquiry_types: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Draft an email reply for inquiry-classified emails using RAG.
    
    This is a pure function (not an HTTP endpoint) called by the 
    email workflow orchestrator when label=inquiry.
    
    Args:
        subject: Original email subject
        body: Original email body e.g., {"department": "Đào tạo"})
        extracted_question: Extracted specific intent to guide the draft
    
    Returns:
        Dict containing:
        - answer: str - Drafted email body
        - question: str - The question extracted (optional)
        - types: List[str] - Categorized types
        - sources: List[Dict] - RAG sources with citations
        - token_usage: Dict - Token statistics (optional)
    
    Raises:
        Exception: If drafting fails
    """
    # Resolve store (request → default store → error)
    store_id_resolved, store_name = await resolve_store(store_id)
    logger.info(f"Drafting email reply using store: {store_name}")

    # Convert metadata filter from dict to Gemini format string
    gemini_filter = convert_metadata_filter_to_gemini_format(metadata_filter)

    # Build additional context
    context_parts = []
    if extracted_question:
        context_parts.append(f"Câu hỏi chính: {extracted_question}")
    if additional_context:
        context_parts.append(additional_context)

    full_context = " | ".join(context_parts) if context_parts else None

    # Generate draft using Gemini RAG
    result = await draft_email_reply(
        original_subject=subject,
        original_body=body,
        additional_context=full_context,
        store_name=store_name,
        metadata_filter=gemini_filter,
    )

    if result is None:
        raise ValueError("Email draft service returned no result from Gemini")

    logger.info(
        f"Email draft generated successfully. "
        f"Sources: {len(result.get('sources', []))} documents"
    )

    if extracted_question:
        result["question"] = extracted_question
    if inquiry_types is not None:
        result["types"] = inquiry_types

    return result
