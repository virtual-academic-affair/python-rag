from app.modules.chat.utils.step_formatter import simplify_step


def test_simplify_query_analysis_shows_only_effective_question():
    step = simplify_step({
        "type": "query_analysis",
        "effective_question": "Giảng viên nộp bảng điểm cuối kỳ theo mẫu nào?",
        "metadata_filter": {
            "enrollment_year": {"from_year": 2022, "to_year": 2022},
        },
    })

    assert step == {
        "type": "query_analysis",
        "content": "Giảng viên nộp bảng điểm cuối kỳ theo mẫu nào?",
    }


def test_simplify_faq_answer_does_not_repeat_question():
    step = simplify_step({
        "type": "faq_answer",
        "answered": True,
        "questions": ["Giảng viên nộp bảng điểm cuối kỳ theo mẫu nào?"],
    })

    assert step == {
        "type": "faq_answer",
        "content": "FAQ trả lời đầy đủ câu hỏi.",
    }
