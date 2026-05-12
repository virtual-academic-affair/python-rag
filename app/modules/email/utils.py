"""Email module utilities for extraction and shared prompt logic."""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

from langchain_core.prompts import ChatPromptTemplate
from app.integrations.llm.gemini import GeminiPromptChain, chain_prompt, GeminiGenAIChat
from app.modules.email.schemas import InquiryFilters
from app.utils.text_utils import remove_accents
from app.utils.json_utils import parse_json_safely
from app.modules.metadata.extraction import extract_metadata_from_text

logger = logging.getLogger(__name__)

async def extract_structured_data(
    llm: GeminiGenAIChat,
    prompt_template: ChatPromptTemplate,
    inputs: dict[str, Any],
    repair_json: bool = True
) -> dict[str, Any]:
    """Helper to run a prompt chain and extract valid JSON from the response."""
    chain = chain_prompt(prompt_template, llm)
    result = await chain.ainvoke(inputs)
    raw_content = result.content or ""
    return parse_json_safely(raw_content, repair=repair_json)


async def extract_inquiry_filters(
    title: str, 
    content: str, 
    metadata_svc: Any = None 
) -> Optional[InquiryFilters]:
    """
    Extract academicYear and enrollmentYear filters using robust static regex pattern matching.
    """
    text_to_search = f"{title} {content}"
    extracted_filters = await extract_metadata_from_text(text_to_search)

    if not extracted_filters:
        return None
    return InquiryFilters(**extracted_filters)
