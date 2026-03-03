"""Service responsible only for label classification."""
import logging
import re

from langchain.prompts import ChatPromptTemplate

from app.models.schemas import SystemLabel
from app.services.orchestration.llm_factory import (
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

    def __init__(self, api_key: str, model: str, temperature: float = 0.1):
        self.llm = build_classification_llm(
            api_key=api_key,
            model=model,
            temperature=temperature,
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
        text = (raw_label or "").strip().lower()
        if not text:
            return SystemLabel.Other.value

        # Keep only letters/underscore/hyphen to handle outputs like:
        # "classRegistration.", "Label: classRegistration", "```classRegistration```"
        compact = re.sub(r"[^a-zA-Z_-]", "", text)
        if compact in cls._VALID_LABELS:
            return compact
        if compact in cls._ALIASES:
            return cls._ALIASES[compact]

        # Fallback: find a valid label token inside longer text
        for token in cls._VALID_LABELS:
            if token.lower() in text:
                return token

        return SystemLabel.Other.value

    async def classify(self, title: str, content: str) -> SystemLabel:
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

            if label == SystemLabel.Other.value and raw_label:
                logger.warning("Could not normalize label from LLM: %r -> other", raw_label)
            return SystemLabel(label)
        except Exception as e:
            logger.error("Label classification failed: %s", str(e), exc_info=True)
            return SystemLabel.Other

