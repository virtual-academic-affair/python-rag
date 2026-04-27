"""Workflow services by label."""

from app.modules.email.workflows.class_registration_service import (
    ClassRegistrationService,
)
from app.modules.email.workflows.inquiry_service import InquiryService

__all__ = [
    "ClassRegistrationService",
    "InquiryService",
]

