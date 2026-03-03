"""Workflow services by label."""

from app.services.orchestration.workflows.class_registration_service import (
    ClassRegistrationService,
)
from app.services.orchestration.workflows.inquiry_service import InquiryService
from app.services.orchestration.workflows.other_service import OtherService
from app.services.orchestration.workflows.task_service import TaskService

__all__ = [
    "ClassRegistrationService",
    "TaskService",
    "InquiryService",
    "OtherService",
]

