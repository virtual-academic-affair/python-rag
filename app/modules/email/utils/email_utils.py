"""Email module utilities for extraction and shared prompt logic."""

from __future__ import annotations

from typing import Any, Optional

from app.modules.email.models.email_types import InquiryFilters
from app.modules.metadata.services.extraction_service import extract_metadata_from_text


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
