import logging

from app.integrations.grpc.client import get_grpc_client
from app.utils.retry import async_retry
from app.modules.email.classification.label_classifier_service import (
    LabelClassifierService,
)
from app.modules.email.workflows.class_registration_service import (
    ClassRegistrationService,
)
from app.modules.email.workflows.inquiry_service import InquiryService
from app.modules.email.schemas import (
    ClassRegistrationExtractResponse,
    InquiryResponse,
    InquiryPayload,
    LabelClassificationResponse,
    ResponseModel,
    SystemLabel,
)

logger = logging.getLogger(__name__)


class EmailWorkflowOrchestrator:
    """Coordinate label classification and workflow execution."""

    _INQUIRY_HINT_KEYWORDS = (
        "hỏi",
        "cho em hỏi",
        "xin hỏi",
        "thắc mắc",
        "thac mac",
        "question",
        "inquiry",
    )

    def __init__(self):
        self.grpc_client = get_grpc_client()
        self.label_classifier = LabelClassifierService()
        self.class_registration_service = ClassRegistrationService()
        self.inquiry_service = InquiryService()

    @classmethod
    def _has_inquiry_intent(cls, title: str, content: str) -> bool:
        combined = f"{title}\n{content}".lower()
        if "?" in combined:
            return True
        return any(keyword in combined for keyword in cls._INQUIRY_HINT_KEYWORDS)

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
        )
        logger.info("Classification result: %s", label.value)

        if label == SystemLabel.ClassRegistration:
            class_reg_content = content
            inquiry_content = content
            if self._has_inquiry_intent(title=title, content=content):
                inquiry_content, class_reg_content = await self.label_classifier.split_mixed_intent_content(
                    title=title,
                    content=content,
                )

            extracted = await self.class_registration_service.process(
                title=title,
                content=class_reg_content,
                message_id=message_id,
            )
            logger.info(
                "classRegistration extracted payload: %s",
                extracted.model_dump_json(by_alias=True, exclude_none=False),
            )
            if self.grpc_client is not None:
                try:
                    grpc_ok = await async_retry(
                        self.grpc_client.create_class_registration,
                        payload=extracted,
                    )
                    if not grpc_ok:
                        logger.warning(
                            "gRPC class registration create failed/rejected for message_id=%s",
                            extracted.message_id,
                        )
                except Exception as grpc_err:
                    logger.warning("gRPC create_class_registration raised exception: %s", grpc_err)

            if self._has_inquiry_intent(title=title, content=content):
                logger.info(
                    "Detected mixed intent (classRegistration + inquiry). Creating inquiry record as well for message_id=%s",
                    message_id,
                )
                draft_result = await self.inquiry_service.process(
                    title=title,
                    content=inquiry_content,
                    message_id=message_id,
                )
                if self.grpc_client is not None and message_id is not None:
                    try:
                        grpc_ok = await async_retry(
                            self.grpc_client.create_inquiry,
                            message_id=message_id,
                            answer=draft_result["answer"],
                            extracted_question=draft_result.get("question"),
                            inquiry_types=draft_result.get("types", []),
                        )
                        if not grpc_ok:
                            logger.warning(
                                "gRPC inquiry create failed/rejected for mixed-intent message_id=%s",
                                message_id,
                            )
                    except Exception as grpc_err:
                        logger.warning("gRPC create_inquiry (mixed-intent) raised exception: %s", grpc_err)

            return ClassRegistrationExtractResponse(
                message_id=message_id,
                label=SystemLabel.ClassRegistration,
                extracted=extracted,
            )

        if label == SystemLabel.Inquiry:
            draft_result = await self.inquiry_service.process(
                title=title,
                content=content,
                message_id=message_id,
            )
            if self.grpc_client is not None and message_id is not None:
                try:
                    grpc_ok = await async_retry(
                        self.grpc_client.create_inquiry,
                        message_id=message_id,
                        answer=draft_result["answer"],
                        extracted_question=draft_result.get("question"),
                        inquiry_types=draft_result.get("types", []),
                    )
                    if not grpc_ok:
                        logger.warning(
                            "gRPC inquiry create failed/rejected for message_id=%s",
                            message_id,
                        )
                except Exception as grpc_err:
                    logger.warning("gRPC create_inquiry raised exception: %s", grpc_err)

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

        return LabelClassificationResponse(label=label, message_id=message_id)

