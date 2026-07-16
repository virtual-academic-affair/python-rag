"""Email query analyzer: normalize subject/body into a RAG-ready query."""
from __future__ import annotations

import logging
from typing import Any, Optional

from app.core.config import settings
from app.integrations.llm.gateway import LLMGateway, get_llm_gateway
from app.modules.metadata.services.extraction_service import extract_metadata_from_text
from app.modules.rag.query.analyzer.contracts import EmailQueryAnalysis
from app.utils.json_utils import parse_json_safely

logger = logging.getLogger(__name__)


EMAIL_QUERY_ANALYZE_SYSTEM_PROMPT = (
    "You analyze academic-affairs emails for a university advisory system.\n"
    "Analyze the email subject and body and extract the following data:\n\n"
    "1. 'question': the user's primary question or core intent.\n"
    "   - Rewrite it as a complete, standalone Vietnamese question.\n"
    "   - Resolve implicit details such as cohort, academic year, and the subject being discussed.\n"
    "   - Preserve the original meaning and language.\n"
    "2. 'inquiry_types': choose values from ['graduation', 'training'].\n"
    "   - 'graduation': graduation eligibility, graduation review, certificates, or degrees.\n"
    "   - 'training': curriculum, courses, registration, schedules, grades, or other academic matters.\n"
    "   - Default to ['training'] when unclear or outside these categories.\n"
    "3. 'metadata_filter': extract academic_year and enrollment_year from the full email context.\n"
    "   - enrollment_year is the student's admission cohort. Mandatory mapping: \"K22\" or \"Khóa 22\" means from_year=2022 and to_year=2022.\n"
    "     Formula: year = 2000 + the number after K. For example, K20=2020, K19=2019, and K22=2022. Do not infer another mapping.\n"
    "   - academic_year is the school year.\n"
    "     + A range such as \"NH 2024-2025\" or \"năm học 24-25\" means from_year=2024 and to_year=2025.\n"
    "     + A single year such as \"năm học 2024\" means from_year=2024 and to_year=2024.\n"
    "     + When enrollment_year K is known and the email mentions study year N for that cohort, calculate from_year = K + N - 1 and to_year = K + N.\n"
    "       * First study year of cohort 22 means academic year 2022-2023.\n"
    "       * Fourth study year of cohort 22 means academic year 2025-2026.\n"
    "   - Use null when the corresponding information is absent.\n\n"
    "Return only one valid JSON object matching this schema, with no surrounding text:\n"
    "{{\n"
    "  \"question\": string,\n"
    "  \"inquiry_types\": [string],\n"
    "  \"metadata_filter\": {{\n"
    "    \"enrollment_year\": {{\n"
    "      \"from_year\": integer,\n"
    "      \"to_year\": integer\n"
    "    }} | null,\n"
    "    \"academic_year\": {{\n"
    "      \"from_year\": integer,\n"
    "      \"to_year\": integer\n"
    "    }} | null\n"
    "  }} | null\n"
    "}}"
)


class EmailQueryAnalyzer:
    """Analyze email subject/body into normalized query intent and filters."""

    def __init__(self, llm_gateway: LLMGateway | None = None):
        self._llm_gateway = llm_gateway or get_llm_gateway()

    async def analyze_email(
        self,
        title: str,
        content: str,
        sender_enrollment_year: int | None = None,
    ) -> EmailQueryAnalysis:
        extraction_data = await self._extract_structured_data(title, content)
        question = extraction_data.get("question")
        inquiry_types = self._normalize_inquiry_types(extraction_data.get("inquiry_types"))
        metadata_filter = self._normalize_metadata_filter(extraction_data.get("metadata_filter"))

        if not metadata_filter.get("enrollment_year") and not metadata_filter.get("academic_year"):
            regex_filter = await extract_metadata_from_text(f"{title} {content}")
            if regex_filter:
                logger.info("[EmailAnalyzer] Fallback metadata extraction: %s", regex_filter)
                metadata_filter.update(regex_filter)

            if not metadata_filter.get("enrollment_year") and sender_enrollment_year:
                logger.info(
                    "[EmailAnalyzer] Fallback enrollment_year to sender cohort: %s",
                    sender_enrollment_year,
                )
                metadata_filter["enrollment_year"] = {
                    "from_year": sender_enrollment_year,
                    "to_year": sender_enrollment_year,
                }

        return EmailQueryAnalysis(
            question=question,
            inquiry_types=inquiry_types,
            metadata_filter=metadata_filter,
        )

    async def _extract_structured_data(self, title: str, content: str) -> dict[str, Any]:
        try:
            response = await self._llm_gateway.complete(
                messages=[
                    {"role": "system", "content": EMAIL_QUERY_ANALYZE_SYSTEM_PROMPT},
                    {"role": "user", "content": f"Email subject: {title}\nEmail body:\n{content}"},
                ],
                model=settings.LLM_MODEL,
                temperature=settings.LLM_DETERMINISTIC_TEMPERATURE,
                response_format={"type": "json_object"},
            )
            return parse_json_safely(response.text or "", repair=True)
        except Exception as exc:
            logger.error("[EmailAnalyzer] Error during email inquiry analysis: %s", exc, exc_info=True)
            return {}

    @staticmethod
    def _normalize_inquiry_types(raw_types: Any) -> list[str]:
        if isinstance(raw_types, str):
            raw_types = [raw_types]
        if not isinstance(raw_types, list):
            return ["training"]

        allowed = {"graduation", "training"}
        normalized = [item for item in raw_types if isinstance(item, str) and item in allowed]
        return normalized or ["training"]

    @staticmethod
    def _normalize_metadata_filter(raw_filter: Any) -> dict[str, Any]:
        if not isinstance(raw_filter, dict):
            return {}

        metadata_filter: dict[str, Any] = {}
        enrollment_year = raw_filter.get("enrollment_year")
        academic_year = raw_filter.get("academic_year")

        if EmailQueryAnalyzer._valid_year_range(enrollment_year):
            metadata_filter["enrollment_year"] = enrollment_year
        if EmailQueryAnalyzer._valid_year_range(academic_year):
            metadata_filter["academic_year"] = academic_year
        return metadata_filter

    @staticmethod
    def _valid_year_range(value: Any) -> bool:
        return (
            isinstance(value, dict)
            and value.get("from_year") is not None
            and value.get("to_year") is not None
        )


_email_query_analyzer_instance: Optional[EmailQueryAnalyzer] = None


def get_email_query_analyzer() -> EmailQueryAnalyzer:
    global _email_query_analyzer_instance
    if _email_query_analyzer_instance is None:
        _email_query_analyzer_instance = EmailQueryAnalyzer()
    return _email_query_analyzer_instance
