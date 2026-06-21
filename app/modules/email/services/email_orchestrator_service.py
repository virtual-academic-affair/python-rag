import asyncio
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
from app.modules.email.models.email_types import (
    ClassRegistrationPayload,
    SystemLabel,
)
from app.modules.email.models.email_out import (
    ClassRegistrationExtractResponse,
    InquiryResponse,
    InquiryPayload,
    LabelClassificationResponse,
    MixedIntentResponse,
    ResponseModel,
)

logger = logging.getLogger(__name__)


class EmailWorkflowOrchestrator:
    """Coordinate label classification and workflow execution."""

    def __init__(self):
        self.grpc_client = get_grpc_client()
        self.label_classifier = LabelClassifierService()
        self.class_registration_service = ClassRegistrationService()
        self.inquiry_service = InquiryService()

    @staticmethod
    def _build_inquiry_payload(draft_result: dict, message_id: int | None) -> InquiryPayload:
        return InquiryPayload(
            answer=draft_result["answer"],
            question=draft_result.get("question"),
            types=draft_result.get("types", []),
            filters=draft_result.get("filters"),
            sources=draft_result["sources"],
            message_id=message_id,
        )

    async def _run_class_registration(
        self,
        title: str,
        content: str,
        message_id: int | None,
    ) -> ClassRegistrationPayload:
        """Extract the class-registration payload and push it to NestJS via gRPC."""
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
        return extracted

    async def _run_inquiry(
        self,
        title: str,
        content: str,
        message_id: int | None,
        student_code: str | None = None,
        enrollment_year: int | None = None,
    ) -> dict:
        """Generate the inquiry reply (RAG) and push it to NestJS via gRPC."""
        draft_result = await self.inquiry_service.process(
            title=title,
            content=content,
            message_id=message_id,
            student_code=student_code,
            enrollment_year=enrollment_year,
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
        return draft_result

    async def process_request(
        self,
        message_id: int | None,
        title: str,
        content: str,
        sender_email: str = "",
        sender_name: str = "",
        student_code: str | None = None,
        enrollment_year: int | None = None,
    ) -> ResponseModel:
        labels = await self.label_classifier.classify_labels(
            title=title,
            content=content,
        )
        logger.info("Classification result: %s", [l.value for l in labels])

        has_class_reg = SystemLabel.ClassRegistration in labels
        has_inquiry = SystemLabel.Inquiry in labels

        # When BOTH labels apply, split the email so each workflow only sees its part.
        # Single-label emails go to their workflow with the full content (no split).
        class_reg_content = content
        inquiry_content = content
        if has_class_reg and has_inquiry:
            inquiry_content, class_reg_content = await self.label_classifier.split_mixed_intent_content(
                title=title,
                content=content,
            )
            logger.info(
                "Mixed intent detected for message_id=%s. Split lengths: inquiry=%d, classRegistration=%d",
                message_id,
                len(inquiry_content),
                len(class_reg_content),
            )

        extracted: ClassRegistrationPayload | None = None
        inquiry_draft: dict | None = None

        cr_coro = None
        inq_coro = None

        if has_class_reg:
            if class_reg_content.strip():
                cr_coro = self._run_class_registration(title, class_reg_content, message_id)
            else:
                logger.warning(
                    "classRegistration label present but split content is empty for message_id=%s; skipping",
                    message_id,
                )
        if has_inquiry:
            if inquiry_content.strip():
                inq_coro = self._run_inquiry(
                    title=title,
                    content=inquiry_content,
                    message_id=message_id,
                    student_code=student_code,
                    enrollment_year=enrollment_year,
                )
            else:
                logger.warning(
                    "inquiry label present but split content is empty for message_id=%s; skipping",
                    message_id,
                )

        if cr_coro and inq_coro:
            import time as _time
            _t0 = _time.perf_counter()
            logger.info(
                "[Orchestrator] Running classRegistration + inquiry in PARALLEL for message_id=%s",
                message_id,
            )
            extracted, inquiry_draft = await asyncio.gather(cr_coro, inq_coro)
            _elapsed = _time.perf_counter() - _t0
            logger.info(
                "[Orchestrator] Both workflows DONE in %.2fs (parallel) for message_id=%s",
                _elapsed,
                message_id,
            )
        elif cr_coro:
            extracted = await cr_coro
        elif inq_coro:
            inquiry_draft = await inq_coro

        if extracted is not None and inquiry_draft is not None:
            return MixedIntentResponse(
                message_id=message_id,
                labels=[SystemLabel.ClassRegistration, SystemLabel.Inquiry],
                extracted=extracted,
                inquiry=self._build_inquiry_payload(inquiry_draft, message_id),
            )
        if extracted is not None:
            return ClassRegistrationExtractResponse(
                message_id=message_id,
                label=SystemLabel.ClassRegistration,
                extracted=extracted,
            )
        if inquiry_draft is not None:
            return InquiryResponse(
                message_id=message_id,
                label=SystemLabel.Inquiry,
                inquiry=self._build_inquiry_payload(inquiry_draft, message_id),
            )

        primary_label = labels[0] if labels else SystemLabel.Inquiry
        return LabelClassificationResponse(label=primary_label, message_id=message_id)
