from __future__ import annotations

from typing import Any

from google.genai import types

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
) -> list[types.Content]:
    faq_context = build_faq_context(faq_docs)
    files_info_str = "\n".join(
        f"[{i + 1}] ID: {c['file_id']} | Name: {c['file_name']} | Description: {c.get('doc_description', '')}"
        for i, c in enumerate(candidate_files)
    )
    prompt_text = (
        f"Ngữ cảnh người dùng: {user_name} (Vai trò: {user_role}, Khóa: {enrollment_year or 'N/A'})\n\n"
        f"{faq_context}"
        "Dưới đây là các tài liệu liên quan được tìm thấy trong cơ sở dữ liệu. "
        "Hãy sử dụng công cụ để đọc nội dung chi tiết bằng cách dùng số thứ tự [n] "
        "trong ngoặc vuông (ví dụ: '1'):\n"
        f"{files_info_str}\n\n"
        f"Câu hỏi của người dùng: {question}"
    )

    history = []
    for item in chat_history[-6:]:
        role = "user" if item.role == "user" else "model"
        history.append(types.Content(role=role, parts=[types.Part.from_text(text=item.content)]))
    history.append(types.Content(role="user", parts=[types.Part.from_text(text=prompt_text)]))
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
        f"- ID: {c['file_id']} | Name: {c['file_name']} | Description: {c.get('doc_description', '')}"
        for c in candidate_files
    )
    context_str = build_metadata_context(metadata_filter)
    return (
        f"Email Subject: {subject}\n"
        f"Email Body:\n{content}\n\n"
        f"{faq_context}"
        f"{context_str}"
        f"Relevant documents found:\n{files_info_str}\n\n"
        f"Please answer the user's specific inquiry based on these documents. "
        f"Respect the specific rules for the given academic year and cohort if provided.\n\n"
        f"Extracted question: {question}"
    )


def build_metadata_context(metadata_filter: dict[str, Any]) -> str:
    context_blocks = []
    if metadata_filter.get("academic_year"):
        academic_year = metadata_filter["academic_year"]
        from_year = academic_year.get("from_year") or academic_year.get("fromYear")
        to_year = academic_year.get("to_year") or academic_year.get("toYear")
        context_blocks.append(f"Academic Year: {from_year}-{to_year}")
    if metadata_filter.get("enrollment_year"):
        enrollment_year = metadata_filter["enrollment_year"]
        from_year = enrollment_year.get("from_year") or enrollment_year.get("fromYear")
        to_year = enrollment_year.get("to_year") or enrollment_year.get("toYear")
        context_blocks.append(f"Enrollment Year: {from_year}-{to_year}")
    return f"Context Information: [{', '.join(context_blocks)}]\n\n" if context_blocks else ""
