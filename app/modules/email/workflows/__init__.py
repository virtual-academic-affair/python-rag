"""Workflow services by label."""

from app.modules.email.workflows.class_registration_service import (
    ClassRegistrationService,
)
from app.modules.email.workflows.inquiry_service import InquiryService
from app.modules.email.workflows.other_service import OtherService
from app.modules.email.workflows.task_service import TaskService

__all__ = [
    "ClassRegistrationService",
    "TaskService",
    "InquiryService",
    "OtherService",
]

