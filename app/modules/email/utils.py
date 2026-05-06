"""Email module utilities for extraction and shared prompt logic."""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

from langchain_core.prompts import ChatPromptTemplate
from app.integrations.llm.gemini import GeminiPromptChain, chain_prompt, GeminiGenAIChat
from app.modules.email.schemas import InquiryFilters
from app.core.text_utils import remove_accents
from app.core.json_utils import parse_json_safely

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
    extracted_filters = {}
    
    text_to_search = f"{title} {content}"
    text_no_accents = remove_accents(text_to_search)

    # 1. Extract Cohort / Enrollment Year (e.g. K22 -> 2022)
    # Match "Khóa 22", "K22", "K.22"
    cohort_pattern = r"(?:khoa\s*|k\s*\.?\s*)(\d{2})\b"
    cohort_match = re.search(cohort_pattern, text_no_accents, re.IGNORECASE)
    if cohort_match:
        val = int(cohort_match.group(1))
        year = 2000 + val if val < 100 else val # handle 22 vs 2022
        extracted_filters["enrollment_year"] = {"fromYear": year, "toYear": year}

    # 2. Extract Academic Year (e.g. 2024-2025)
    # Match "năm học 2024-2025", "nh 24-25"
    ay_pattern = r"(?:nam\s*hoc|nh|nien\s*khoa|nk)\s*(\d{2,4})[\s\-\/]+(\d{2,4})\b"
    ay_match = re.search(ay_pattern, text_no_accents, re.IGNORECASE)
    if ay_match:
        y1 = int(ay_match.group(1))
        y2 = int(ay_match.group(2))
        y1 = 2000 + y1 if y1 < 100 else y1
        y2 = 2000 + y2 if y2 < 100 else y2
        extracted_filters["academic_year"] = {"fromYear": y1, "toYear": y2}
    else:
        # Match single year "năm học 2024"
        ay_single_pattern = r"(?:nam\s*hoc|nh|nien\s*khoa|nk)\s*(\d{4})\b"
        ay_single_match = re.search(ay_single_pattern, text_no_accents, re.IGNORECASE)
        if ay_single_match:
            y = int(ay_single_match.group(1))
            extracted_filters["academic_year"] = {"fromYear": y, "toYear": y}

    if not extracted_filters:
        return None
    return InquiryFilters(**extracted_filters)
