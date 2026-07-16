from app.modules.rag.query.answering.pageindex_agent.prompt_builder import build_email_prompt_text
from app.modules.rag.query.answering.pageindex_agent.prompts import (
    BASE_PAGEINDEX_SYSTEM_PROMPT,
    CHAT_SYSTEM_PROMPT,
    EMAIL_SYSTEM_PROMPT,
)


def test_pageindex_prompts_enforce_tool_and_answer_contracts():
    assert "get_document_structure" in BASE_PAGEINDEX_SYSTEM_PROMPT
    assert "call `get_page_content" in BASE_PAGEINDEX_SYSTEM_PROMPT
    assert "exactly one short Vietnamese sentence" in BASE_PAGEINDEX_SYSTEM_PROMPT
    assert "Do not cite every sentence" in BASE_PAGEINDEX_SYSTEM_PROMPT
    assert "without a greeting" in CHAT_SYSTEM_PROMPT.lower()
    assert "conversation history" in CHAT_SYSTEM_PROMPT
    assert "Answer the normalized question directly" in EMAIL_SYSTEM_PROMPT
    assert "email" not in EMAIL_SYSTEM_PROMPT.lower()
    assert CHAT_SYSTEM_PROMPT != EMAIL_SYSTEM_PROMPT


def test_email_prompt_uses_english_numbered_document_context():
    prompt = build_email_prompt_text(
        question="Điều kiện tốt nghiệp là gì?",
        subject="Hỏi tốt nghiệp",
        content="Em cần biết điều kiện.",
        metadata_filter={
            "enrollment_year": {"from_year": 2022, "to_year": 2022},
        },
        candidate_files=[{
            "file_id": "file-1",
            "file_name": "Quy chế đào tạo",
            "doc_description": "Quy định tốt nghiệp",
        }],
        faq_docs=[],
    )

    assert "Subject: Hỏi tốt nghiệp" in prompt
    assert "Original email body:\nEm cần biết điều kiện." in prompt
    assert "Question to answer: Điều kiện tốt nghiệp là gì?" in prompt
    assert "[1] ID: file-1" in prompt
    assert "Enrollment years: 2022-2022" in prompt
    assert "soạn" not in prompt.lower()
    assert "trả lời email" not in prompt.lower()
