"""Orchestrator that routes email to workflow by label."""
import asyncio
import logging

from app.models.schemas import (
    ClassRegistrationExtractResponse,
    InternalData,
    LabelClassificationResponse,
    ResponseModel,
    SystemLabel,
    TaskExtractResponse,
)
from app.services.integrations.grpc_client import GrpcLabelClient
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

    def __init__(
        self,
        api_key: str,
        model: str,
        temperature: float = 0.1,
        grpc_label_client: GrpcLabelClient | None = None,
    ):
        self.grpc_label_client = grpc_label_client
        self.label_classifier = LabelClassifierService(
            api_key=api_key,
            model=model,
            temperature=temperature,
            grpc_label_client=grpc_label_client,
        )
        self.class_registration_service = ClassRegistrationService(
            api_key=api_key,
            model=model,
            temperature=temperature,
        )
        self.task_service = TaskService(
            api_key=api_key,
            model=model,
            temperature=temperature,
        )
        self.inquiry_service = InquiryService()
        self.other_service = OtherService()

    async def process_request(
        self, internal_data: InternalData, title: str, content: str
    ) -> ResponseModel:
        label = await self.label_classifier.classify(
            title=title,
            content=content,
            internal_data=internal_data,
        )
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
            if self.grpc_label_client is not None:
                grpc_ok = await self.grpc_label_client.create_class_registration(
                    payload=extracted,
                )
                if not grpc_ok:
                    logger.warning(
                        "gRPC class registration create failed/rejected for message_id=%s",
                        extracted.message_id,
                    )
            return ClassRegistrationExtractResponse(
                internal=internal_data,
                label=SystemLabel.ClassRegistration,
                extracted=extracted,
            )

        if label == SystemLabel.Task:
            extracted = await self.task_service.process(
                title=title,
                content=content,
                message_id=message_id,
            )
            logger.info(
                "task extracted payload: %s",
                extracted.model_dump_json(by_alias=True, exclude_none=False),
            )
            if self.grpc_label_client is not None:
                resolved_assignee_ids: list[int] = []
                seen_ids: set[int] = set()
                keywords = [item.strip() for item in (extracted.assignee_ids or []) if item.strip()]

                tasks = [
                    self.grpc_label_client.find_auth_user_by_keyword(keyword)
                    for keyword in keywords
                ]
                results = await asyncio.gather(*tasks, return_exceptions=True)

                for result in results:
                    if isinstance(result, Exception) or not result:
                        continue
                    user_id = result.get("id")
                    if isinstance(user_id, int) and user_id not in seen_ids:
                        seen_ids.add(user_id)
                        resolved_assignee_ids.append(user_id)

                extracted.assignee_ids = resolved_assignee_ids
                grpc_ok = await self.grpc_label_client.create_task(payload=extracted)
                if not grpc_ok:
                    logger.warning(
                        "gRPC task create failed/rejected for message_id=%s",
                        extracted.message_id,
                    )

            return TaskExtractResponse(
                internal=internal_data,
                label=SystemLabel.Task,
                extracted=extracted,
            )
        if label == SystemLabel.Inquiry:
            await self.inquiry_service.process(title=title, content=content, message_id=message_id)
        else:
            await self.other_service.process(title=title, content=content, message_id=message_id)

        return LabelClassificationResponse(internal=internal_data, label=label)

