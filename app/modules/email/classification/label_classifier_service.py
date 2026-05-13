"""Service responsible only for label classification."""
import json
import logging
import re

from langchain_core.prompts import ChatPromptTemplate

from app.modules.email.schemas import SystemLabel
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
        SystemLabel.Inquiry.value,
    }

    _ALIASES = {
        "classregistration": SystemLabel.ClassRegistration.value,
        "class_registration": SystemLabel.ClassRegistration.value,
        "class-registration": SystemLabel.ClassRegistration.value,
        "registration": SystemLabel.ClassRegistration.value,
        "register": SystemLabel.ClassRegistration.value,
        "inquiry": SystemLabel.Inquiry.value,
        "question": SystemLabel.Inquiry.value,
    }

    _CLASS_REG_KEYWORDS = [
        "đăng ký học phần",
        "dang ky hoc phan",
        "xin mở lớp",
        "mo lop",
        "hủy học phần",
        "huy hoc phan",
        "đổi lớp",
        "doi lop",
        "thêm môn",
        "them mon",
        "bớt môn",
        "bot mon",
    ]

    def __init__(self):
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
- inquiry

Label definitions:
1) classRegistration
- Student requests related to course/class registration operations.
- Typical intents: đăng ký học phần, hủy học phần, đổi lớp, xin mở lớp, thêm/bớt môn, trùng lịch học, lớp đầy, điều kiện tiên quyết, mã môn/lớp học phần.
- Also classify as classRegistration when student expresses actionable intent in natural language, e.g. "muốn học cải thiện ...", "muốn học lại ...", "xin đăng ký lớp ...".

2) inquiry
- Student asks for information, clarification, guidance, policy explanation.
- Mostly Q&A, consultation, status checking; no explicit execution request like register/cancel/open class.
- Examples: "học cải thiện là gì?", "điều kiện học lại như thế nào?", "khi nào mở đăng ký?".

Decision priority (very important):
- If there is any actionable request to perform registration operation now -> classRegistration.
- If content is only asking policy/information without requesting execution -> inquiry.
- Do not be biased by the presence of student profile lines (name, MSSV, class).

Few-shot guidance:
Input: "Em muốn học cải thiện môn Nhập môn lập trình 22C01"
Output: classRegistration

Input: "Cho em hỏi quy định học cải thiện môn Nhập môn lập trình"
Output: inquiry

Output constraints:
- Return ONLY one raw label token: classRegistration OR inquiry.
- No explanation, no punctuation, no markdown, no extra words.
- If uncertain, return inquiry.
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

        self.mixed_split_prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    """You split a student email into 2 focused parts for downstream workflows.
Return STRICT JSON ONLY with this schema:
{"inquiry_content":"...","class_registration_content":"..."}
Rules:
- inquiry_content: only question/consultation/policy clarification intent.
- class_registration_content: only actionable registration intent (register/cancel/open/switch class, course code/class code, constraints).
- If a sentence belongs to both, keep it in both.
- Preserve original language.
- No markdown, no explanation.
""",
                ),
                (
                    "human",
                    """[EMAIL_TITLE]
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
            return SystemLabel.Inquiry.value

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

        return SystemLabel.Inquiry.value

    async def split_mixed_intent_content(
        self,
        title: str,
        content: str,
    ) -> tuple[str, str]:
        """Use LLM to split mixed-intent email content into inquiry/class-registration parts."""
        try:
            chain = chain_prompt(self.mixed_split_prompt, self.llm)
            result = await chain.ainvoke({"title": title, "content": content})
            raw = (result.content or "").strip()
            logger.info("[MIXED SPLIT RESULT] raw=%r", raw)

            data = json.loads(raw)
            inquiry_content = str(data.get("inquiry_content") or "").strip()
            class_registration_content = str(data.get("class_registration_content") or "").strip()

            if not inquiry_content:
                inquiry_content = content
            if not class_registration_content:
                class_registration_content = content

            return inquiry_content, class_registration_content
        except Exception as e:
            logger.warning("LLM mixed-intent split failed, fallback to original content: %s", e)
            return content, content

    async def classify(
        self,
        title: str,
        content: str,
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
            if any(kw in combined_text for kw in self._CLASS_REG_KEYWORDS):
                if label != SystemLabel.ClassRegistration.value:
                    logger.warning(
                        "[CLASSIFY HEURISTIC] Override %s -> classRegistration due to explicit registration keywords",
                        label,
                    )
                label = SystemLabel.ClassRegistration.value

            logger.info("[CLASSIFY RESULT] normalized_label=%s", label)
            return SystemLabel(label)
        except Exception as e:
            logger.error("Label classification failed: %s", str(e), exc_info=True)
            return SystemLabel.Inquiry

