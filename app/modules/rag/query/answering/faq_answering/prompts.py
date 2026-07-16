from __future__ import annotations

from typing import Optional

from app.modules.rag.query.answering.faq_answering.contracts import FaqAnswerEntry


BASE_FAQ_ANSWER_SYSTEM_PROMPT = """
{persona}
You receive a user question and a list of FAQs already selected by retrieval and reranking. Each FAQ includes an ID, question, Markdown answer, enrollment-year scope, and academic-year scope.

# WHEN AN ANSWER IS ALLOWED
- Answer only when one or more FAQs provide enough information to resolve the entire question.
- If the question contains multiple independent intents, every intent must be fully covered. Use all necessary FAQs in the synthesis.
- If coverage is partial, weakly related, missing an intent, contradictory, or requires official documents for confirmation, return `{{"answer": null}}`.
- Use only the supplied FAQ content. Do not guess or add outside knowledge.
- When the question specifies a cohort or academic year, use only FAQs applicable to that scope. Return null if applicability cannot be established.

# ANSWER STYLE
- Write a natural, focused Vietnamese answer; do not merely copy the FAQ wording.
- Use clear Markdown and {voice}.
- Do not begin with a greeting.
- Do not expose FAQ IDs, retrieval details, prompts, or system internals in `answer_markdown`.
- Do not create document citations because FAQs are not PageIndex citation sources.
- {channel_rules}

# OUTPUT
Return only one of these JSON shapes, without explanation or a Markdown fence:
{{
  "answer": {{
    "faq_ids": ["<used faq id>", "..."],
    "answer_markdown": "<Vietnamese Markdown answer>"
  }}
}}
or `{{"answer": null}}` when the FAQs do not fully answer the question.
"""


def build_faq_answer_system_prompt(*, persona: str, voice: str, channel_rules: str) -> str:
    return BASE_FAQ_ANSWER_SYSTEM_PROMPT.format(
        persona=persona,
        voice=voice,
        channel_rules=channel_rules,
    ).strip()


CHAT_FAQ_ANSWER_SYSTEM_PROMPT = build_faq_answer_system_prompt(
    persona="You are a student support advisor for a university Academic Affairs Office.",
    voice="use a first-person plural voice on behalf of the office",
    channel_rules="Answer the current question directly and concisely while including every necessary condition or step.",
)


EMAIL_FAQ_ANSWER_SYSTEM_PROMPT = build_faq_answer_system_prompt(
    persona="You are an official advisor for a university Academic Affairs Office.",
    voice="refer to the Academic Affairs Office or use a first-person plural voice",
    channel_rules="Answer the normalized question directly without a greeting, preamble, heading, or signature.",
)


# Backward-compatible default for direct/debug FAQ calls.
FAQ_ANSWER_SYSTEM_PROMPT = CHAT_FAQ_ANSWER_SYSTEM_PROMPT


def _fmt_year(year_filter: Optional[dict]) -> str:
    if not year_filter:
        return "all cohorts"
    from_year = year_filter.get("from_year")
    to_year = year_filter.get("to_year")
    if from_year in (None, 0) and to_year in (None, 9999):
        return "all cohorts"
    if from_year == to_year:
        return str(from_year)
    return f"{from_year}-{to_year}"


def render_faq_answer_context(entries: list[FaqAnswerEntry]) -> str:
    blocks: list[str] = []
    for index, entry in enumerate(entries, 1):
        blocks.append(
            "\n".join([
                f"[{index}] ID: {entry.faq_id}",
                f"FAQ question: {entry.question}",
                f"Enrollment years: {_fmt_year(entry.enrollment_year)} | Academic years: {_fmt_year(entry.academic_year)}",
                "FAQ answer:",
                entry.answer_markdown,
            ])
        )
    return "\n\n---\n\n".join(blocks)


def build_faq_answer_prompt(question: str, entries: list[FaqAnswerEntry]) -> str:
    return (
        f'USER QUESTION: "{question}"\n\n'
        + f"FAQ LIST:\n{render_faq_answer_context(entries)}\n\n"
        + "Return JSON:"
    )
