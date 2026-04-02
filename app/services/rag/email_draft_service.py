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
from app.models.schemas import InquiryIntent, InquiryTypesResult, InquiryFilters
from app.repositories.file_repository import FileRepository
from app.services.rag.utils.file_utils import remove_accents
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


class EmailDraftService:
    """
    Service for generating email replies using RAG.
    """
    
    def __init__(self):
        self._file_repo = None

    @property
    def file_repo(self) -> FileRepository:
        """Lazy load file repository."""
        if self._file_repo is None:
            self._file_repo = FileRepository()
        return self._file_repo

    async def draft_email_reply(
        self,
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
        file_search_config = types.FileSearch(
            fileSearchStoreNames=[store_name],
            metadataFilter=metadata_filter
        )
        
        config.tools = [
            types.Tool(fileSearch=file_search_config)
        ]
        
        # Native async Gemini call
        response = await gemini_client.client.aio.models.generate_content(
            model=settings.GEMINI_MODEL,
            contents=full_prompt,
            config=config,
        )
        
        answer = response.text or ""
        
        sources, chunk_map = extract_sources(response)
        sources = sources or []
        
        if answer and chunk_map:
            answer = inject_citations(answer, response, chunk_map)
        
        sources = await enrich_sources_with_urls(sources, self.file_repo) or []
        
        return {
            "answer": answer,
            "sources": sources,
            "token_usage": extract_token_usage(response),
        }

    async def extract_inquiry_intent(self, subject: str, body: str) -> Optional[str]:
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
            # Native async Gemini call
            response = await gemini_client.client.aio.models.generate_content(
                model=settings.GEMINI_MODEL,
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

    async def extract_inquiry_types(self, subject: str, body: str) -> Optional[List[str]]:
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
            # Native async Gemini call
            response = await gemini_client.client.aio.models.generate_content(
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

    async def extract_inquiry_filters(self, subject: str, body: str) -> Optional[InquiryFilters]:
        """
        Extract academicYear and cohort filters using robust rule-based pattern matching.
        Fetches allowed values from DB, then uses regex to find them in the email text.
        Supports accented and accent-less Vietnamese.
        """
        import re
        from app.services.rag.metadata_service import get_metadata_service
        metadata_service = get_metadata_service()
        
        subject = subject or ""
        body = body or ""
        
        extracted_filters = {}
        
        for key in ["academic_year", "cohort"]:
            try:
                meta_type = await metadata_service.get_metadata_type(key)
            except Exception as e:
                logger.warning("Failed to fetch metadata type '%s': %s", key, e)
                continue
            if not meta_type or not meta_type.is_active:
                continue
                
            allowed_values = meta_type.get_allowed_values() or []
            
            # Check subject first (higher priority), then body
            for text in [subject, body]:
                if not text:
                    continue
                text_no_accents = remove_accents(text)
                
                matched_value = None
                for av in allowed_values:
                    if not av.is_active or av.value == "all":
                        continue
                    
                    patterns = self._build_filter_patterns(key, av)
                    
                    for p in patterns:
                        if not p:
                            continue
                        # Try accented match first
                        if re.search(p, text, re.IGNORECASE):
                            matched_value = av.value
                            break
                        # Then try accent-less match
                        p_no_accents = remove_accents(p)
                        if re.search(p_no_accents, text_no_accents, re.IGNORECASE):
                            matched_value = av.value
                            break
                    if matched_value:
                        break
                
                if matched_value:
                    extracted_filters[key] = matched_value
                    break  # Found in subject or body, stop for this key
                    
        if not extracted_filters:
            return None
        return InquiryFilters(**extracted_filters)

    @staticmethod
    def _build_filter_patterns(key: str, av) -> list[str]:
        """
        Build a list of regex patterns for a given metadata key and allowed value.
        Returns patterns ordered from most specific to least specific.
        """
        import re as _re
        patterns = []
        
        if key == "academic_year":
            # value is like "2024-2025"
            if '-' not in av.value:
                # Fallback: just match the raw value
                return [_re.escape(av.value)]
            
            y1, y2 = av.value.split('-', 1)
            s1, s2 = y1[-2:], y2[-2:]
            sep = r"[\s\-\/]+"
            
            # Prefixed patterns (most specific — require a Vietnamese keyword before the year)
            # Added "năm\s*" and "nam\s*" to handle "năm 2024-2025"
            pre = r"(năm\s*học|nh|niên\s*khóa|niên\s*khoá|nk|nam\s*hoc|nien\s*khoa|năm|nam)\s*"
            patterns.extend([
                rf"{pre}{y1}{sep}{y2}",          # năm học 2024-2025
                rf"{pre}{s1}{sep}{s2}",          # NH 24-25  (safe: requires prefix)
                rf"{pre}{y1}{sep}{s2}",          # năm học 2024-25
                rf"{pre}{y1}\b",                 # năm học 2024 (just first year)
            ])
            
            # Full year without prefix (still safe: 4 digit + separator + 4 digit is unambiguous)
            patterns.append(rf"\b{y1}{sep}{y2}\b")
            
        elif key == "cohort":
            # value is like "K20"
            m = _re.search(r"K?(\d+)", av.value, _re.IGNORECASE)
            if m:
                d = m.group(1)
                # With prefix (safe)
                pre = r"(khóa|khoá|khoa)\s*"
                patterns.extend([
                    rf"{pre}K?{d}\b",          # Khóa 20, Khóa K20
                    rf"\bK\.?\s*{d}\b",        # K20, K.20, K 20
                ])
                # Support full year for 2-digit cohort (e.g., "khóa 2022" for K22)
                if len(d) == 2:
                    patterns.append(rf"{pre}20{d}\b")
            
        # Fallback: exact value and display_name (with word boundaries to avoid partial matches like "Khóa 20" matching "Khóa 2022")
        patterns.append(rf"\b{_re.escape(av.value)}\b")
        if av.display_name:
            patterns.append(rf"\b{_re.escape(av.display_name)}\b")
        
        return patterns

    async def draft_inquiry_email_reply(
        self,
        subject: str,
        body: str,
        additional_context: Optional[str] = None,
        store_id: Optional[str] = None,
        metadata_filter: Optional[Dict[str, Any]] = None,
        extracted_question: Optional[str] = None,
        inquiry_types: Optional[List[str]] = None,
        inquiry_filters: Optional[InquiryFilters] = None,
    ) -> Dict[str, Any]:
        """
        Draft an email reply for inquiry-classified emails using RAG.
        """
        # Resolve store (request → default store → error)
        store_id_resolved, store_name = await resolve_store(store_id)
        logger.info(f"Drafting email reply using store: {store_name}")

        # Convert metadata filter using standardized utility
        gemini_filter = convert_metadata_filter_to_gemini_format(metadata_filter)

        # Build additional context
        context_parts = []
        if extracted_question:
            context_parts.append(f"Câu hỏi chính: {extracted_question}")
        if additional_context:
            context_parts.append(additional_context)

        full_context = " | ".join(context_parts) if context_parts else None

        # Generate draft using internal method
        result = await self.draft_email_reply(
            original_subject=subject,
            original_body=body,
            additional_context=full_context,
            store_name=store_name,
            metadata_filter=gemini_filter,
        )

        if result is None:
            raise ValueError("Email draft service returned no result from LLM")

        logger.info(
            f"Email draft generated successfully. "
            f"Sources: {len(result.get('sources', []))} documents"
        )

        if extracted_question:
            result["question"] = extracted_question
        if inquiry_types is not None:
            result["types"] = inquiry_types
        if inquiry_filters is not None:
            result["filters"] = inquiry_filters

        return result

_email_draft_service_instance: Optional[EmailDraftService] = None

def get_email_draft_service() -> EmailDraftService:
    """Get singleton instance of EmailDraftService."""
    global _email_draft_service_instance
    if _email_draft_service_instance is None:
        _email_draft_service_instance = EmailDraftService()
    return _email_draft_service_instance

async def draft_inquiry_email_reply(*args, **kwargs):
    """Legacy wrapper for the new service method."""
    return await get_email_draft_service().draft_inquiry_email_reply(*args, **kwargs)

async def extract_inquiry_intent(*args, **kwargs):
    """Legacy wrapper for the new service method."""
    return await get_email_draft_service().extract_inquiry_intent(*args, **kwargs)

async def extract_inquiry_types(*args, **kwargs):
    """Legacy wrapper for the new service method."""
    return await get_email_draft_service().extract_inquiry_types(*args, **kwargs)

async def extract_inquiry_filters(*args, **kwargs):
    """Legacy wrapper for the new service method."""
    return await get_email_draft_service().extract_inquiry_filters(*args, **kwargs)
