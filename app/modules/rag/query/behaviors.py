from app.modules.rag.query.answering.faq_answering import (
    CHAT_FAQ_ANSWER_SYSTEM_PROMPT,
    EMAIL_FAQ_ANSWER_SYSTEM_PROMPT,
)
from app.modules.rag.query.answering.pageindex_agent import CHAT_SYSTEM_PROMPT, EMAIL_SYSTEM_PROMPT
from app.modules.rag.query.contracts import RagQueryBehavior


CHAT_BEHAVIOR = RagQueryBehavior(
    mode="chat",
    analyzer_mode="chat",
    allow_direct_reply=True,
    allow_enrollment_fallback=True,
    include_reasoning=True,
    system_prompt=CHAT_SYSTEM_PROMPT,
    faq_system_prompt=CHAT_FAQ_ANSWER_SYSTEM_PROMPT,
    no_candidate_message="Không tìm thấy tài liệu nào phù hợp với yêu cầu của bạn.",
)

CHAT_STREAM_BEHAVIOR = RagQueryBehavior(
    mode="chat",
    analyzer_mode="chat",
    allow_direct_reply=True,
    allow_enrollment_fallback=True,
    include_reasoning=True,
    system_prompt=CHAT_SYSTEM_PROMPT,
    faq_system_prompt=CHAT_FAQ_ANSWER_SYSTEM_PROMPT,
    no_candidate_message="Không tìm thấy tài liệu nào phù hợp với yêu cầu của bạn.",
)

EMAIL_BEHAVIOR = RagQueryBehavior(
    mode="email",
    analyzer_mode="email",
    allow_direct_reply=False,
    allow_enrollment_fallback=False,
    include_reasoning=False,
    system_prompt=EMAIL_SYSTEM_PROMPT,
    faq_system_prompt=EMAIL_FAQ_ANSWER_SYSTEM_PROMPT,
    no_candidate_message="Không tìm thấy tài liệu phù hợp để trả lời email này.",
)
