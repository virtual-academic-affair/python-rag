from __future__ import annotations

from typing import Any

from app.modules.rag.query.retrieval.hydration import build_faq_context


def build_chat_prompt_contents(
    *,
    question: str,
    user_name: str,
    user_role: str,
    enrollment_year: int | None,
    chat_history: list[Any],
    candidate_files: list[dict[str, Any]],
    faq_docs: list[Any],
) -> list[dict[str, Any]]:
    faq_context = build_faq_context(faq_docs)
    files_info_str = "\n".join(
        f"[{i + 1}] ID: {c['file_id']} | Name: {c['file_name']} | Description: {c.get('doc_description', '')}"
        for i, c in enumerate(candidate_files)
    )
    prompt_text = (
        f"User context: {user_name} (Role: {user_role}, Enrollment year: {enrollment_year or 'N/A'})\n\n"
        f"{faq_context}"
        "The following candidate documents were found in the database. "
        "Use the tools to read their detailed content and identify documents by their [n] index, "
        "for example '1':\n"
        f"{files_info_str}\n\n"
        f"User question: {question}"
    )

    history: list[dict[str, Any]] = []
    for item in chat_history[-6:]:
        role = "user" if item.role == "user" else "assistant"
        history.append({"role": role, "content": item.content})
    history.append({"role": "user", "content": prompt_text})
    return history


def build_email_prompt_text(
    *,
    question: str,
    subject: str,
    content: str,
    metadata_filter: dict[str, Any],
    candidate_files: list[dict[str, Any]],
    faq_docs: list[Any],
) -> str:
    faq_context = build_faq_context(faq_docs)
    files_info_str = "\n".join(
        f"[{i + 1}] ID: {c['file_id']} | Name: {c['file_name']} | Description: {c.get('doc_description', '')}"
        for i, c in enumerate(candidate_files)
    )
    context_str = build_metadata_context(metadata_filter)
    return (
        f"Subject: {subject}\n"
        f"Original email body:\n{content}\n\n"
        f"Question to answer: {question}\n\n"
        f"{faq_context}"
        f"{context_str}"
        f"Candidate documents:\n{files_info_str}\n\n"
        "Use the [n] index to read the correct documents and answer the question directly in Vietnamese. "
        "Apply the supplied academic-year and enrollment-year scope exactly."
    )


def build_metadata_context(metadata_filter: dict[str, Any]) -> str:
    context_blocks = []
    if metadata_filter.get("academic_year"):
        academic_year = metadata_filter["academic_year"]
        from_year = academic_year.get("from_year") or academic_year.get("fromYear")
        to_year = academic_year.get("to_year") or academic_year.get("toYear")
        context_blocks.append(f"Academic years: {from_year}-{to_year}")
    if metadata_filter.get("enrollment_year"):
        enrollment_year = metadata_filter["enrollment_year"]
        from_year = enrollment_year.get("from_year") or enrollment_year.get("fromYear")
        to_year = enrollment_year.get("to_year") or enrollment_year.get("toYear")
        context_blocks.append(f"Enrollment years: {from_year}-{to_year}")
    return f"Applicable scope: [{', '.join(context_blocks)}]\n\n" if context_blocks else ""
