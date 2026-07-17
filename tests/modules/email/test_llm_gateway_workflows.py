import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.integrations.llm.contracts import LLMResponse
from app.modules.email.classification.label_classifier_service import LabelClassifierService
from app.modules.email.models.email_types import SystemLabel
from app.modules.email.workflows.class_registration_service import ClassRegistrationService
from app.modules.email.workflows.task_service import TaskService


def _response(payload: object) -> LLMResponse:
    text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    return LLMResponse(
        text=text,
        tool_calls=[],
        assistant_message={"role": "assistant", "content": text},
    )


@pytest.mark.asyncio
async def test_label_classifier_uses_system_and_user_messages():
    gateway = SimpleNamespace(complete=AsyncMock(return_value=_response('["inquiry"]')))
    service = LabelClassifierService(llm_gateway=gateway)

    labels = await service.classify_labels("Hỏi học phí", "Cho em hỏi quy định học phí")

    assert labels == [SystemLabel.Inquiry]
    messages = gateway.complete.await_args.kwargs["messages"]
    assert [message["role"] for message in messages] == ["system", "user"]
    assert "assign ALL applicable labels" in messages[0]["content"]
    assert "Hỏi học phí" in messages[1]["content"]
    assert "Cho em hỏi quy định học phí" in messages[1]["content"]


@pytest.mark.asyncio
async def test_mixed_intent_split_renders_json_schema_without_template_braces():
    gateway = SimpleNamespace(complete=AsyncMock(return_value=_response({
        "inquiry_content": "Điều kiện là gì?",
        "class_registration_content": "Em muốn đăng ký lớp 22C01.",
    })))
    service = LabelClassifierService(llm_gateway=gateway)

    result = await service.split_mixed_intent_content("Đăng ký", "Nội dung hỗn hợp")

    assert result == ("Điều kiện là gì?", "Em muốn đăng ký lớp 22C01.")
    messages = gateway.complete.await_args.kwargs["messages"]
    assert [message["role"] for message in messages] == ["system", "user"]
    assert '{{"inquiry_content"' not in messages[0]["content"]
    assert '{"inquiry_content"' in messages[0]["content"]
    assert gateway.complete.await_args.kwargs["response_format"] == {"type": "json_object"}


@pytest.mark.asyncio
async def test_class_registration_extraction_uses_complete_prompt_contract():
    gateway = SimpleNamespace(complete=AsyncMock(return_value=_response({
        "messageId": 123,
        "status": "",
        "studentCode": "22123456",
        "academicYear": 2025,
        "studentName": "Nguyễn Văn A",
        "note": "",
        "items": [{
            "action": "register",
            "subjectName": "Nhập môn lập trình",
            "className": "22C01",
            "subjectCode": "",
            "slotInfo": "",
            "isInCurriculum": False,
        }],
    })))
    service = ClassRegistrationService(llm_gateway=gateway)

    payload = await service.process("Đăng ký lớp", "Em muốn đăng ký lớp 22C01", 123)

    assert payload.message_id == 123
    assert payload.items[0].class_name == "22C01"
    messages = gateway.complete.await_args.kwargs["messages"]
    assert [message["role"] for message in messages] == ["system", "user"]
    assert '"messageId": number|null' in messages[0]["content"]
    assert "[INPUT_MESSAGE_ID]\n123" in messages[1]["content"]
    assert "Em muốn đăng ký lớp 22C01" in messages[1]["content"]


@pytest.mark.asyncio
async def test_task_extraction_uses_shared_extraction_profile():
    gateway = SimpleNamespace(complete=AsyncMock(return_value=_response({
        "name": "Chuẩn bị báo cáo",
        "description": "Tổng hợp số liệu",
        "due": None,
        "priority": "medium",
        "assigners": ["Phòng Đào tạo"],
        "assigneeIds": ["Lan"],
        "messageId": 9,
    })))
    service = TaskService(llm_gateway=gateway)

    payload = await service.process("Giao việc", "Giao cô Lan chuẩn bị báo cáo", 9)

    assert payload.name == "Chuẩn bị báo cáo"
    assert payload.assignee_ids == ["Lan"]
    messages = gateway.complete.await_args.kwargs["messages"]
    assert [message["role"] for message in messages] == ["system", "user"]
    assert '"assigneeIds": [string]' in messages[0]["content"]
    assert gateway.complete.await_args.kwargs["response_format"] == {"type": "json_object"}
