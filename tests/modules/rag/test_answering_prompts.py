from app.modules.rag.query.answering.pageindex_agent.prompt_builder import build_email_prompt_text
from app.modules.rag.query.answering.pageindex_agent.prompts import (
    BASE_PAGEINDEX_SYSTEM_PROMPT,
    CHAT_SYSTEM_PROMPT,
    EMAIL_SYSTEM_PROMPT,
)


def test_pageindex_prompts_enforce_tool_and_answer_contracts():
    assert "get_document_structure" in BASE_PAGEINDEX_SYSTEM_PROMPT
    assert "bắt buộc dùng `get_page_content" in BASE_PAGEINDEX_SYSTEM_PROMPT
    assert "đúng một câu tiếng Việt ngắn" in BASE_PAGEINDEX_SYSTEM_PROMPT
    assert "Không chèn citation sau từng câu" in BASE_PAGEINDEX_SYSTEM_PROMPT
    assert "không dùng câu chào" in CHAT_SYSTEM_PROMPT.lower()
    assert "lịch sử hội thoại" in CHAT_SYSTEM_PROMPT
    assert "Trả lời trực tiếp câu hỏi đã chuẩn hóa" in EMAIL_SYSTEM_PROMPT
    assert "email" not in EMAIL_SYSTEM_PROMPT.lower()
    assert CHAT_SYSTEM_PROMPT != EMAIL_SYSTEM_PROMPT


def test_email_prompt_uses_vietnamese_numbered_document_context():
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
    assert "Nội dung email gốc:\nEm cần biết điều kiện." in prompt
    assert "Câu hỏi cần trả lời: Điều kiện tốt nghiệp là gì?" in prompt
    assert "[1] ID: file-1" in prompt
    assert "Khóa sinh viên: 2022-2022" in prompt
    assert "soạn" not in prompt.lower()
    assert "trả lời email" not in prompt.lower()
