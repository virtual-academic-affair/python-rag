"""Orchestrator that routes email to workflow by label."""
import logging

from app.models.schemas import (
    ClassRegistrationExtractResponse,
    InternalData,
    LabelClassificationResponse,
    ResponseModel,
    SystemLabel,
)
from app.services.orchestration.classification.label_classifier_service import (
    LabelClassifierService,
)
from app.services.orchestration.workflows.class_registration_service import (
    ClassRegistrationService,
)
from app.services.orchestration.workflows.inquiry_service import InquiryService
from app.services.orchestration.workflows.other_service import OtherService
from app.services.orchestration.workflows.task_service import TaskService

logger = logging.getLogger(__name__)


class EmailWorkflowOrchestrator:
    """Coordinate label classification and workflow execution."""

    def __init__(self, api_key: str, model: str, temperature: float = 0.1):
        self.label_classifier = LabelClassifierService(
            api_key=api_key,
            model=model,
            temperature=temperature,
        )
        self.class_registration_service = ClassRegistrationService(
            api_key=api_key,
            model=model,
            temperature=temperature,
        )
        self.task_service = TaskService()
        self.inquiry_service = InquiryService()
        self.other_service = OtherService()

    async def process_request(
        self, internal_data: InternalData, title: str, content: str
    ) -> ResponseModel:
        label = await self.label_classifier.classify(title=title, content=content)
        logger.info("Classification result: %s", label.value)

        message_id = int(internal_data.mail_id) if str(internal_data.mail_id).isdigit() else None

        if label == SystemLabel.ClassRegistration:
            extracted = await self.class_registration_service.process(
                title=title,
                content=content,
                message_id=message_id,
            )
            logger.info(
                "classRegistration extracted payload: %s",
                extracted.model_dump_json(by_alias=True, exclude_none=False),
            )
            return ClassRegistrationExtractResponse(
                internal=internal_data,
                label=SystemLabel.ClassRegistration,
                extracted=extracted,
            )

        if label == SystemLabel.Task:
            await self.task_service.process(title=title, content=content, message_id=message_id)
        elif label == SystemLabel.Inquiry:
            await self.inquiry_service.process(title=title, content=content, message_id=message_id)
        else:
            await self.other_service.process(title=title, content=content, message_id=message_id)

        return LabelClassificationResponse(internal=internal_data, label=label)

