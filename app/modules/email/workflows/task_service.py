"""Workflow service for task label."""
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
from app.integrations.grpc.client import get_grpc_client
from app.modules.email.schemas import TaskPayload
from app.core.json_utils import parse_json_safely

logger = logging.getLogger(__name__)


class TaskService:
    """Extract structured task payload from email."""

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
                    """You are an information extraction engine for task-related emails.
Your job is to produce ONE strict JSON object following this exact schema (ALL keys required, even if empty):

{{
  "name": string,
  "description": string,
  "due": string|null,
  "priority": "low"|"medium"|"high"|"urgent",
  "assigners": [string],
  "assigneeIds": [string],
  "messageId": number|null
}}

Extraction policy:
1) Preserve factual values from email only. Do NOT invent facts.
2) If missing/uncertain:
   - string -> ""
   - number -> null
   - list -> []
3) messageId must be copied from provided input messageId if available.
4) due must be ISO-8601 string in UTC if provided, else null.
5) assigneeIds MUST extract search keywords for assignee lookup from explicit assignment phrases (e.g., "giao cho", "phân công", "assign to").
6) For assigneeIds, keep ONLY core person names or emails. Remove honorifics/titles/pronouns such as "bạn", "anh", "chị", "cô", "thầy", "ông", "bà", "Mr", "Ms", "Dr".
7) Do NOT rewrite assignee into descriptive forms; only return plain lookup tokens (example: "bạn Tài" -> "Tài", "cô Lan" -> "Lan").
8) Always output a COMPLETE JSON object with all keys present; do not truncate.
9) If the email is long, summarize description to <= 240 characters so the JSON fits.

Field rules (for RAG search):
- name: the task title assigned in the email.
- description: concise summary; include all bullet items in one line separated by "; ".
- due: the task deadline.
- priority: the task importance level.
- assigners: people/teams assigning the task extracted from the email.
- assigneeIds: assignee lookup keywords only (plain names/emails) explicitly assigned the task. Strip honorifics/titles and keep only the core name token(s) for ID matching.
- messageId: copy from input messageId.

Normalization rules:
- priority:
  - urgent: urgent, ASAP, extremely urgent, highest priority.
  - high: urgent, important, high priority.
  - medium: normal, medium priority.
  - low: not urgent, low priority.
  - if no clue: "medium".
- assigners: teams/departments/people requesting the task.

Output constraints:
- Return VALID JSON object only on a single line.
- No markdown, no code fence, no explanation, no trailing text.
- All keys must be exactly as schema (camelCase).
""",
                ),
                (
                    "human",
                    """Extract task payload from this email.

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

        # Removed local JSON extraction and repair helpers. Using app.core.json_utils instead.

    async def process(self, title: str, content: str, message_id: int | None = None) -> TaskPayload:
        try:
            rendered_messages = self.extract_prompt.format_messages(
                title=title,
                content=content,
                message_id=message_id,
            )
            logger.info("[TASK EXTRACT PROMPT] Sending %d messages to LLM", len(rendered_messages))
            for idx, msg in enumerate(rendered_messages, start=1):
                logger.info(
                    "[TASK EXTRACT PROMPT][%d][%s]\n%s",
                    idx,
                    msg.__class__.__name__,
                    getattr(msg, "content", ""),
                )

            chain = chain_prompt(self.extract_prompt, self.llm)
            result = await chain.ainvoke(
                {"title": title, "content": content, "message_id": message_id}
            )
            logger.info("[TASK EXTRACT RESULT] raw=%r", result.content)

            payload_dict = parse_json_safely(result.content or "", repair=True)
            logger.info("[TASK EXTRACT RESULT] parsed_dict=%s", payload_dict)

            payload = TaskPayload.model_validate(payload_dict)
            if message_id is not None:
                payload.message_id = message_id
            return payload
        except Exception as e:
            logger.error("Task extraction failed: %s", str(e), exc_info=True)
            return TaskPayload(messageId=message_id)

