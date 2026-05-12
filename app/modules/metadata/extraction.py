"""
Utility for extracting metadata filters from text using regex patterns.
"""
import re
import logging
from typing import Optional, Dict, Any
from app.utils.text_utils import remove_accents
from app.modules.metadata.schemas import YearRangeSchema

logger = logging.getLogger(__name__)

async def extract_metadata_from_text(text: str) -> Dict[str, Any]:
    """
    Extract academicYear and enrollmentYear filters from text using robust static regex pattern matching.
    Returns a dict compatible with InquiryFilters/FaqMetadataSchema.
    """
    extracted_filters = {}
    
    if not text:
        return extracted_filters
        
    text_no_accents = remove_accents(text)

    # 1. Extract Cohort / Enrollment Year (e.g. K22 -> 2022, Khóa 65 -> 2020)
    # Match "Khóa 22", "K22", "K.22"
    # Note: Logic for cohort to year: K65 is roughly 2020. 
    # Current project pattern from email/utils.py: year = 2000 + val if val < 100 else val
    cohort_pattern = r"(?:khoa\s*|k\s*\.?\s*)(\d{2,4})\b"
    cohort_matches = re.finditer(cohort_pattern, text_no_accents, re.IGNORECASE)
    
    for match in cohort_matches:
        val = int(match.group(1))
        # Logic to convert cohort to year if needed, but here we just take the year as is or 2000+val
        # The existing logic in email/utils.py was: year = 2000 + val if val < 100 else val
        year = 2000 + val if val < 100 else val
        extracted_filters["enrollment_year"] = {"from_year": year, "to_year": year}
        break # Take the first match

    # 2. Extract Academic Year (e.g. 2024-2025, nh 24-25)
    ay_pattern = r"(?:nam\s*hoc|nh|nien\s*khoa|nk)\s*(\d{2,4})[\s\-\/]+(\d{2,4})\b"
    ay_match = re.search(ay_pattern, text_no_accents, re.IGNORECASE)
    if ay_match:
        y1 = int(ay_match.group(1))
        y2 = int(ay_match.group(2))
        y1 = 2000 + y1 if y1 < 100 else y1
        y2 = 2000 + y2 if y2 < 100 else y2
        extracted_filters["academic_year"] = {"from_year": y1, "to_year": y2}
    else:
        # Match single year "năm học 2024"
        ay_single_pattern = r"(?:nam\s*hoc|nh|nien\s*khoa|nk)\s*(\d{4})\b"
        ay_single_match = re.search(ay_single_pattern, text_no_accents, re.IGNORECASE)
        if ay_single_match:
            y = int(ay_single_match.group(1))
            extracted_filters["academic_year"] = {"from_year": y, "to_year": y}

    return extracted_filters
