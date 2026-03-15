"""Workflow service for task label."""
import json
import logging
import re

from langchain.prompts import ChatPromptTemplate

from app.models.schemas import TaskPayload
from app.services.orchestration.llm_factory import (
    build_extraction_llm,
    chain_prompt,
    env_thinking_level,
)

logger = logging.getLogger(__name__)


class TaskService:
    """Extract structured task payload from email."""

    def __init__(self, api_key: str, model: str, temperature: float = 0.1):
        self.llm = build_extraction_llm(
            api_key=api_key,
            model=model,
            temperature=temperature,
            thinking_level=env_thinking_level(),
        )

        self.extract_prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    """You are an information extraction engine for task-related emails.
Your job is to produce ONE strict JSON object following this exact schema:

{
  "name": string,
  "description": string,
  "due": string|null,
  "priority": "low"|"medium"|"high"|"urgent",
  "assigners": [string],
  "assigneeIds": [string],
  "messageId": number|null
}

Extraction policy:
1) Preserve factual values from email only. Do NOT invent facts.
2) If missing/uncertain:
   - string -> ""
   - number -> null
   - list -> []
3) messageId must be copied from provided input messageId if available.
4) due must be ISO-8601 string in UTC if provided, else null.

Field rules (for RAG search):
- name: the task title assigned in the email.
- description: detailed task description from the email.
- due: the task deadline.
- priority: the task importance level.
- assigners: people/teams assigning the task extracted from the email.
- assigneeIds: assignee info (name/email). Always return string values for lookup.
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
- Return VALID JSON object only.
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

    @staticmethod
    def _extract_json_object(raw: str) -> str:
        text = (raw or "").strip()
        match = re.search(r"\{[\s\S]*\}", text)
        return match.group(0) if match else "{}"

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

            json_str = self._extract_json_object(result.content or "")
            logger.info("[TASK EXTRACT RESULT] parsed_json=%s", json_str)

            payload = TaskPayload.model_validate(json.loads(json_str))
            if message_id is not None:
                payload.message_id = message_id
            return payload
        except Exception as e:
            logger.error("Task extraction failed: %s", str(e), exc_info=True)
            return TaskPayload(messageId=message_id)

