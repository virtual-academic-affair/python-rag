"""Email module utilities for extraction and shared prompt logic."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from langchain_core.prompts import ChatPromptTemplate
from app.integrations.llm.gemini import GeminiPromptChain, chain_prompt, GeminiGenAIChat
from app.modules.email.schemas import InquiryFilters

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
    
    json_str = _extract_json_object(raw_content)
    if repair_json:
        json_str = _repair_truncated_json(json_str)
        
    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        logger.error(f"Failed to decode JSON: {json_str}")
        return {}

def _extract_json_object(raw: str) -> str:
    """Extract first balance JSON object from raw string."""
    text = str(raw).strip()
    if not text:
        return "{}"
    
    # Strip markdown fences
    text = re.sub(r"```(?:json)?\s*([\s\S]*?)\s*```", r"\1", text, flags=re.IGNORECASE).strip()
    
    start = text.find("{")
    if start == -1:
        return "{}"
        
    depth = 0
    in_string = False
    escaped = False
    end = -1
    
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
            
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i
                break
                
    if end != -1:
        return text[start : end + 1]
    return "{}"

def _repair_truncated_json(json_str: str) -> str:
    """Basic repair for truncated JSON responses."""
    if not json_str or json_str == "{}":
        return json_str
    
    in_string = False
    escape = False
    brace_balance = 0
    
    for char in json_str:
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
        else:
            if char == '"':
                in_string = True
            elif char == "{":
                brace_balance += 1
            elif char == "}":
                brace_balance -= 1
                
    repaired = json_str
    if in_string:
        repaired += '"'
    if brace_balance > 0:
        repaired += "}" * brace_balance
        
    # Remove trailing commas before closing braces/brackets
    repaired = re.sub(r",\s*([}\]])", r"\1", repaired)
    return repaired

def remove_accents(input_str: str) -> str:
    """
    Remove Vietnamese accents from a string.
    Example: 'năm học' -> 'nam hoc'
    """
    if not input_str:
        return ""
    import unicodedata
    # Normalize to NFD (Decomposition)
    s = unicodedata.normalize('NFD', input_str)
    # Filter out non-spacing marks (accents)
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
    # Replace special characters like đ/Đ
    s = s.replace('đ', 'd').replace('Đ', 'D')
    return unicodedata.normalize('NFC', s)

async def extract_inquiry_filters(
    title: str, 
    content: str, 
    metadata_svc: Any # Using Any to avoid circular import if type hint is needed
) -> Optional[InquiryFilters]:
    """
    Extract academicYear and cohort filters using robust rule-based pattern matching.
    Ported from legacy store-free RAG logic.
    """
    extracted_filters = {}
    
    for key in ["academic_year", "cohort"]:
        meta_type = await metadata_svc.get_metadata_type(key)
        if not meta_type or not meta_type.is_active:
            continue
            
        allowed_values = meta_type.get_allowed_values() or []
        
        # Check title first (higher priority), then content
        for text in [title, content]:
            if not text:
                continue
            text_no_accents = remove_accents(text)
            
            matched_value = None
            for av in allowed_values:
                if not av.is_active or av.value == "all":
                    continue
                
                patterns = _build_filter_patterns(key, av)
                
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
                break
                
    if not extracted_filters:
        return None
    return InquiryFilters(**extracted_filters)

def _build_filter_patterns(key: str, av: Any) -> list[str]:
    """
    Build a list of regex patterns for a given metadata key and allowed value.
    Ordered from most specific to least specific.
    """
    patterns = []
    
    if key == "academic_year":
        # value is like "2024-2025"
        if '-' not in av.value:
            return [re.escape(av.value)]
        
        y1, y2 = av.value.split('-', 1)
        s1, s2 = y1[-2:], y2[-2:]
        sep = r"[\s\-\/]+"
        
        # Prefixed patterns
        pre = r"(năm\s*học|nh|niên\s*khóa|niên\s*khoá|nk|nam\s*hoc|nien\s*khoa|năm|nam)\s*"
        patterns.extend([
            rf"{pre}{y1}{sep}{y2}",          # năm học 2024-2025
            rf"{pre}{s1}{sep}{s2}",          # NH 24-25
            rf"{pre}{y1}{sep}{s2}",          # năm học 2024-25
            rf"{pre}{y1}\b",                 # năm học 2024
        ])
        # Full year without prefix
        patterns.append(rf"\b{y1}{sep}{y2}\b")
        
    elif key == "cohort":
        # value is like "K20"
        m = re.search(r"K?(\d+)", av.value, re.IGNORECASE)
        if m:
            d = m.group(1)
            pre = r"(khóa|khoá|khoa)\s*"
            patterns.extend([
                rf"{pre}K?{d}\b",          # Khóa 20, Khóa K20
                rf"\bK\.?\s*{d}\b",        # K20, K.20, K 20
            ])
            if len(d) == 2:
                patterns.append(rf"{pre}20{d}\b") # khóa 2022 -> K22
        
    # Fallback: exact value and display_name
    patterns.append(rf"\b{re.escape(av.value)}\b")
    if av.display_name:
        patterns.append(rf"\b{re.escape(av.display_name)}\b")
    
    return patterns
