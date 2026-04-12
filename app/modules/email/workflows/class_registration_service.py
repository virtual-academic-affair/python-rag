"""Workflow service for classRegistration label."""
import json
import logging
import re

from langchain_core.prompts import ChatPromptTemplate

from app.core.config import settings
from app.integrations.llm.gemini import (
    build_extraction_llm,
    chain_prompt,
    env_thinking_level,
)
from app.modules.email.schemas import ClassRegistrationPayload

logger = logging.getLogger(__name__)


class ClassRegistrationService:
    """Extract structured class registration payload from email."""

    def __init__(self):
        self.llm = build_extraction_llm(
            api_key=settings.GOOGLE_API_KEY,
            model=settings.GEMINI_MODEL,
            temperature=0.1,
            thinking_level=env_thinking_level(),
        )

        self.extract_prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    """You are an information extraction engine for university class registration emails.
Your job is to produce ONE strict JSON object following this exact schema:

{{
  "messageId": number|null,
  "status": string,
  "studentCode": string,
  "academicYear": number|null,
  "studentName": string,
  "note": string,
  "items": [
    {{
      "action": "register"|"cancel"|"requestOpen",
      "subjectName": string,
      "className": string,
      "subjectCode": string,
      "slotInfo": string,
      "isInCurriculum": boolean
    }}
  ]
}}

Extraction policy:
1) Preserve factual values from email only. Do NOT invent facts.
2) If missing/uncertain:
   - string -> ""
   - number -> null
   - boolean -> false
   - list -> []
3) messageId must be copied from provided input messageId if available.
4) status should be empty string unless email explicitly provides a status keyword.
5) items can contain multiple operations when email mentions many subjects/classes.

Action mapping rules (critical):
- action="register": add/register/enroll học phần, thêm môn, đăng ký lớp.
- action="cancel": cancel/drop/withdraw/hủy học phần, rút môn.
- action="requestOpen": đề nghị/xin mở lớp, mở thêm lớp, mở lớp mới do lớp đầy/chưa có lớp.
- Never output any action outside: register, cancel, requestOpen.

Field normalization rules:
- studentCode: student ID/MSSV if present.
- studentName: full student name if present.
- academicYear: numeric year (e.g., 2025), not string; if term text only and no year -> null.
- note: concise free-text note from email (payment reason, urgency, constraints...).
- slotInfo: keep schedule text as in email (e.g., "Thứ 2, tiết 1-3").
- isInCurriculum:
  - true only when explicitly indicates in-program/in curriculum/chương trình đào tạo.
  - otherwise false.

Output constraints (must follow):
- Return VALID JSON object only.
- No markdown, no code fence, no explanation, no trailing text.
- All keys must be exactly as schema (camelCase).
""",
                ),
                (
                    "human",
                    """Extract class registration payload from this email.

[INPUT_MESSAGE_ID]
{message_id}

[EMAIL_TITLE]
{title}

[EMAIL_CONTENT]
{content}
""",
                ),
            ]
        )

    @staticmethod
    def _extract_json_object(raw: str) -> str:
        text = (raw or "").strip()
        if not text:
            return "{}"

        # Strip markdown code fences if present
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text).strip()

        # Prefer strict JSON decode from the first '{'
        start = text.find("{")
        if start >= 0:
            candidate = text[start:]
            try:
                obj, _ = json.JSONDecoder().raw_decode(candidate)
                return json.dumps(obj, ensure_ascii=False)
            except Exception:
                pass

        # Fallback: extract first balanced {...} block (quote-aware)
        start = text.find("{")
        if start < 0:
            return "{}"

        depth = 0
        in_string = False
        escaped = False
        end = -1

        for i, ch in enumerate(text[start:], start=start):
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

        if end > start:
            return text[start : end + 1]

        return "{}"

    async def process(self, title: str, content: str, message_id: int | None) -> ClassRegistrationPayload:
        try:
            rendered_messages = self.extract_prompt.format_messages(
                title=title,
                content=content,
                message_id=message_id,
            )
            logger.info("[EXTRACT PROMPT] Sending %d messages to LLM", len(rendered_messages))
            for idx, msg in enumerate(rendered_messages, start=1):
                logger.info(
                    "[EXTRACT PROMPT][%d][%s]\n%s",
                    idx,
                    msg.__class__.__name__,
                    getattr(msg, "content", ""),
                )

            chain = chain_prompt(self.extract_prompt, self.llm)
            result = await chain.ainvoke(
                {"title": title, "content": content, "message_id": message_id}
            )
            logger.info("[EXTRACT RESULT] raw=%r", result.content)

            json_str = self._extract_json_object(result.content or "")
            logger.info("[EXTRACT RESULT] parsed_json=%s", json_str)

            payload = ClassRegistrationPayload.model_validate(json.loads(json_str))
            if message_id is not None:
                payload.message_id = message_id
            payload.note = ""
            return payload
        except Exception as e:
            logger.error("ClassRegistration extraction failed: %s", str(e), exc_info=True)
            return ClassRegistrationPayload(messageId=message_id)

