"""Service responsible only for label classification."""
import logging
import re

from langchain_core.prompts import ChatPromptTemplate

from app.modules.email.schemas import SystemLabel
from app.integrations.grpc.client import get_grpc_client
from app.core.config import settings
from app.integrations.llm.gemini import (
    build_classification_llm,
    chain_prompt,
    env_thinking_level,
)

logger = logging.getLogger(__name__)


class LabelClassifierService:
    """Classify email into one of supported SystemLabel values."""

    _VALID_LABELS = {
        SystemLabel.ClassRegistration.value,
        SystemLabel.Task.value,
        SystemLabel.Inquiry.value,
        SystemLabel.Other.value,
    }

    _ALIASES = {
        "classregistration": SystemLabel.ClassRegistration.value,
        "class_registration": SystemLabel.ClassRegistration.value,
        "class-registration": SystemLabel.ClassRegistration.value,
        "registration": SystemLabel.ClassRegistration.value,
        "register": SystemLabel.ClassRegistration.value,
        "task": SystemLabel.Task.value,
        "todo": SystemLabel.Task.value,
        "inquiry": SystemLabel.Inquiry.value,
        "question": SystemLabel.Inquiry.value,
        "other": SystemLabel.Other.value,
    }

    _CLASS_REG_KEYWORDS = [
        "đăng ký học phần",
        "dang ky hoc phan",
        "học phần",
        "hoc phan",
        "xin mở lớp",
        "mo lop",
        "hủy học phần",
        "huy hoc phan",
        "mã học phần",
        "ma hoc phan",
    ]

    def __init__(self):
        self.grpc_client = get_grpc_client()
        self.llm = build_classification_llm(
            api_key=settings.GOOGLE_API_KEY,
            model=settings.GEMINI_MODEL,
            temperature=0.1,
            thinking_level=env_thinking_level(),
        )

        self.classification_prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    """You are a senior email triage assistant for a university academic office.
Your task: classify each incoming email into EXACTLY ONE label:
- classRegistration
- task
- inquiry
- other

Label definitions:
1) classRegistration
- Student requests related to course/class registration operations.
- Typical intents: đăng ký học phần, hủy học phần, đổi lớp, xin mở lớp, thêm/bớt môn, trùng lịch học, lớp đầy, điều kiện tiên quyết, mã môn/lớp học phần.

2) task
- Work assignment/request from internal units (department/office/faculty/admin) for the academic office to execute.
- Usually operational or coordination tasks, not student personal Q&A.

3) inquiry
- Student asks for information, clarification, guidance, policy explanation.
- Mostly Q&A, consultation, status checking; no explicit execution request like register/cancel/open class.

4) other
- Irrelevant, unclear, spam, greetings only, missing context, or not fitting above labels.

Decision priority (very important):
- If registration intent appears clearly -> classRegistration.
- Else if internal cross-department execution request -> task.
- Else if student question/clarification -> inquiry.
- Else -> other.

Output constraints:
- Return ONLY one raw label token: classRegistration OR task OR inquiry OR other.
- No explanation, no punctuation, no markdown, no extra words.
- If uncertain, return other.
""",
                ),
                (
                    "human",
                    """Classify the following email.

[EMAIL_TITLE]
{title}

[EMAIL_CONTENT]
{content}
""",
                ),
            ]
        )

    @classmethod
    def _normalize_label(cls, raw_label: str) -> str:
        text = (raw_label or "").strip()
        if not text:
            return SystemLabel.Other.value

        # Clean markdown backticks and single quotes that Gemini sometimes adds
        # E.g. "'classRegistration'", "`inquiry`"
        clean_text = re.sub(r"['\"`]", "", text)
        
        # Exact match (case insensitive)
        for token in cls._VALID_LABELS:
            if clean_text.lower() == token.lower():
                return token

        text_lower = text.lower()
        
        # Check aliases
        compact = re.sub(r"[^a-zA-Z_-]", "", text_lower)
        if compact in cls._ALIASES:
            return cls._ALIASES[compact]

        # Fallback: substring match on original cleaned text
        for token in cls._VALID_LABELS:
            if token.lower() in text_lower:
                return token

        return SystemLabel.Other.value

    async def classify(
        self,
        title: str,
        content: str,
        message_id: int | None = None,
    ) -> SystemLabel:
        try:
            rendered_messages = self.classification_prompt.format_messages(
                title=title,
                content=content,
            )
            logger.info("[CLASSIFY PROMPT] Sending %d messages to LLM", len(rendered_messages))
            for idx, msg in enumerate(rendered_messages, start=1):
                logger.info(
                    "[CLASSIFY PROMPT][%d][%s]\n%s",
                    idx,
                    msg.__class__.__name__,
                    getattr(msg, "content", ""),
                )

            chain = chain_prompt(self.classification_prompt, self.llm)
            result = await chain.ainvoke({"title": title, "content": content})
            raw_label = (result.content or "").strip()
            logger.info("[CLASSIFY RESULT] raw_label=%r", raw_label)

            label = self._normalize_label(raw_label)

            combined_text = f"{title}\n{content}".lower()
            if label == SystemLabel.Other.value and any(
                kw in combined_text for kw in self._CLASS_REG_KEYWORDS
            ):
                logger.warning(
                    "[CLASSIFY HEURISTIC] Override other -> classRegistration due to strong registration keywords"
                )
                label = SystemLabel.ClassRegistration.value

            logger.info("[CLASSIFY RESULT] normalized_label=%s", label)

            if self.grpc_client is not None and message_id is not None:
                try:
                    grpc_ok = await self.grpc_client.update_label(
                        message_id=message_id,
                        label=SystemLabel(label),
                        title=title,
                    )
                    if not grpc_ok:
                        logger.warning(
                            "gRPC label update failed/rejected in classifier for message_id=%s",
                            message_id,
                        )
                except Exception as grpc_err:
                    logger.warning("gRPC update_label raised exception for message_id=%s: %s", message_id, grpc_err)

            if label == SystemLabel.Other.value and raw_label:
                logger.warning("Could not normalize label from LLM: %r -> other", raw_label)
            return SystemLabel(label)
        except Exception as e:
            logger.error("Label classification failed: %s", str(e), exc_info=True)
            return SystemLabel.Other

