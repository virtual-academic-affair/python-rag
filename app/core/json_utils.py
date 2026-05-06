"""
JSON utilities for extracting and repairing structured data from LLM responses.
"""
import json
import logging
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)

def extract_json_object(raw: str) -> str:
    """Extract first balanced JSON object from raw string."""
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

def repair_truncated_json(json_str: str) -> str:
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

def parse_json_safely(json_str: str, repair: bool = True) -> dict[str, Any]:
    """Extract, repair, and parse JSON safely."""
    clean_json = extract_json_object(json_str)
    if repair:
        clean_json = repair_truncated_json(clean_json)
        
    try:
        return json.loads(clean_json)
    except json.JSONDecodeError:
        logger.error(f"Failed to decode JSON: {clean_json}")
        return {}
