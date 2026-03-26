"""Orchestrator that routes email to workflow by label."""
import asyncio
import logging

from app.models.schemas import (
    ClassRegistrationExtractResponse,
    InquiryResponse,
    InquiryPayload,
    LabelClassificationResponse,
    ResponseModel,
    SystemLabel,
    TaskExtractResponse,
)
from app.services.integrations.grpc_client import GrpcClient
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
        grpc_client: GrpcClient | None = None,
    ):
        self.grpc_client = grpc_client
        self.label_classifier = LabelClassifierService(
            api_key=api_key,
            model=model,
            temperature=temperature,
            grpc_client=grpc_client,
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
        self,
        message_id: int | None,
        title: str,
        content: str,
        sender_email: str = "",
        sender_name: str = "",
    ) -> ResponseModel:
        label = await self.label_classifier.classify(
            title=title,
            content=content,
            message_id=message_id,
        )
        logger.info("Classification result: %s", label.value)

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
            if self.grpc_client is not None:
                grpc_ok = await self.grpc_client.create_class_registration(
                    payload=extracted,
                )
                if not grpc_ok:
                    logger.warning(
                        "gRPC class registration create failed/rejected for message_id=%s",
                        extracted.message_id,
                    )
            return ClassRegistrationExtractResponse(
                message_id=message_id,
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
            if self.grpc_client is not None:
                resolved_assignee_ids: list[int] = []
                seen_ids: set[int] = set()
                keywords = [item.strip() for item in (extracted.assignee_ids or []) if item.strip()]

                tasks = [
                    self.grpc_client.find_auth_user_by_keyword(keyword)
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
                grpc_ok = await self.grpc_client.create_task(payload=extracted)
                if not grpc_ok:
                    logger.warning(
                        "gRPC task create failed/rejected for message_id=%s",
                        extracted.message_id,
                    )

            return TaskExtractResponse(
                message_id=message_id,
                label=SystemLabel.Task,
                extracted=extracted,
            )

        if label == SystemLabel.Inquiry:
            draft_result = await self.inquiry_service.process(
                title=title,
                content=content,
                message_id=message_id,
            )
            return InquiryResponse(
                message_id=message_id,
                label=SystemLabel.Inquiry,
                inquiry=InquiryPayload(
                    answer=draft_result["answer"],
                    question=draft_result.get("question"),
                    types=draft_result.get("types", []),
                    filters=draft_result.get("filters"),
                    sources=draft_result["sources"],
                    message_id=message_id,
                ),
            )

        if label == SystemLabel.Other:
            await self.other_service.process(title=title, content=content, message_id=message_id)

        return LabelClassificationResponse(label=label, message_id=message_id)

