"""Common gRPC client for external integration calls.

Keep all gRPC methods in this file. Services can call the corresponding
method they need (e.g. update_label, notify_task, ...).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from importlib import import_module

import grpc
from google.protobuf.json_format import MessageToDict

from app.models.schemas import InternalData, SystemLabel


class GrpcInquiryClient:
    def __init__(self, config: GrpcClientConfig):
        self._config = config

    async def create_inquiry(
        self,
        message_id: int,
        draft_body: str,
        extracted_question: str | None = None,
        inquiry_types: list[str] | None = None,
    ) -> bool:
        if not self._config.enabled:
            return False
        target = f"{self._config.host}:{self._config.port}"
        try:
            from importlib import import_module

            pb2 = import_module("app.proto.inquiry.inquiry_pb2")
            pb2_grpc = import_module("app.proto.inquiry.inquiry_pb2_grpc")
            async with grpc.aio.insecure_channel(target) as channel:
                stub = pb2_grpc.InquiryServiceStub(channel)
                
                kwargs = {
                    "messageId": message_id,
                    "answer": draft_body,
                }
                if extracted_question is not None:
                    kwargs["question"] = extracted_question
                if inquiry_types is not None:
                    kwargs["types"] = inquiry_types
                
                request = pb2.CreateInquiryRequest(**kwargs)
                response = await stub.Create(request, timeout=self._config.timeout_seconds)
                logger.info("Inquiry created via gRPC for messageId=%s", message_id)
                return response.success
        except grpc.aio.AioRpcError as exc:
            if exc.code() == grpc.StatusCode.UNIMPLEMENTED:
                logger.warning(
                    "InquiryService.Create is not yet implemented on nest-api (messageId=%s). Skipping.",
                    message_id,
                )
            else:
                logger.warning("gRPC InquiryService.Create failed: %s — %s", exc.code(), exc.details())
            return False
        except Exception as exc:
            logger.warning("gRPC Inquiry unexpected error: %s", exc)
            return False

logger = logging.getLogger(__name__)


@dataclass
class GrpcClientConfig:
    enabled: bool
    host: str
    port: int
    timeout_seconds: float


class GrpcClient:
    """Shared gRPC client used by multiple services."""

    def __init__(self, config: GrpcClientConfig):
        self._config = config
        self._stubs: dict[str, object] = {}
        self._requests: dict[str, object] = {}
        self._load_stubs()

    def _load_stubs(self) -> None:
        """Load generated protobuf stubs at runtime.

        Expected generated modules:
        - app/proto/label/label_pb2.py
        - app/proto/label/label_pb2_grpc.py
        """
        try:
            pb2 = import_module("app.proto.label.label_pb2")
            pb2_grpc = import_module("app.proto.label.label_pb2_grpc")
            self._requests["update_labels"] = pb2.UpdateLabelsRequest
            self._stubs["message"] = pb2_grpc.MessageServiceStub
        except Exception as exc:
            logger.warning(
                "gRPC stubs are not available yet. Run proto generation first. Details: %s",
                exc,
            )
        try:
            pb2 = import_module("app.proto.class_registration.class_registration_pb2")
            pb2_grpc = import_module("app.proto.class_registration.class_registration_pb2_grpc")
            self._requests["class_registration_create"] = pb2.CreateRegistrationRequest
            self._stubs["class_registration"] = pb2_grpc.ClassRegistrationServiceStub
        except Exception as exc:
            logger.warning(
                "Class registration gRPC stubs are not available yet. Run proto generation first. Details: %s",
                exc,
            )

        try:
            pb2 = import_module("app.proto.auth.auth_pb2")
            pb2_grpc = import_module("app.proto.auth.auth_pb2_grpc")
            self._requests["auth_find_one_by_keyword"] = pb2.FindOneByKeywordRequest
            self._requests["auth_verify_token"] = pb2.VerifyTokenRequest
            self._stubs["auth"] = pb2_grpc.AuthServiceStub
        except Exception as exc:
            logger.warning(
                "Auth gRPC stubs are not available yet. Run proto generation first. Details: %s",
                exc,
            )

        try:
            pb2 = import_module("app.proto.task.task_pb2")
            pb2_grpc = import_module("app.proto.task.task_pb2_grpc")
            self._requests["task_create"] = pb2.CreateTaskRequest
            self._stubs["task"] = pb2_grpc.TaskServiceStub
        except Exception as exc:
            logger.warning(
                "Task gRPC stubs are not available yet. Run proto generation first. Details: %s",
                exc,
            )

    @property
    def is_ready(self) -> bool:
        return self._config.enabled and bool(self._stubs)

    async def _call(self, *, service_key: str, rpc_name: str, request) -> object | None:
        if not self._config.enabled:
            return None
        stub_cls = self._stubs.get(service_key)
        if stub_cls is None:
            logger.warning("Skip gRPC call %s because service '%s' is not ready", rpc_name, service_key)
            return None

        target = f"{self._config.host}:{self._config.port}"
        try:
            async with grpc.aio.insecure_channel(target) as channel:
                stub = stub_cls(channel)
                rpc = getattr(stub, rpc_name)
                return await rpc(request, timeout=self._config.timeout_seconds)
        except Exception as exc:
            logger.error("gRPC call %s failed: %s", rpc_name, exc, exc_info=True)
            return None

    async def update_label(
        self,
        *,
        internal_data: InternalData,
        label: SystemLabel,
        title: str | None = None,
    ) -> bool:
        """Service method: update classified label to external system."""
        _ = title
        if not self._config.enabled:
            return True

        request_cls = self._requests.get("update_labels")
        if request_cls is None:
            logger.warning("Skip gRPC label update because request class is not ready")
            return False

        message_id = int(internal_data.mail_id) if str(internal_data.mail_id).isdigit() else None
        if message_id is None:
            logger.warning(
                "Skip gRPC label update because mail_id is not numeric: %s",
                internal_data.mail_id,
            )
            return False

        request = request_cls(
            messageId=message_id,
            systemLabels=[label.value],
        )
        logger.info(
            "gRPC update_labels request: %s",
            MessageToDict(request, preserving_proto_field_name=True),
        )
        response = await self._call(
            service_key="message",
            rpc_name="UpdateLabels",
            request=request,
        )
        if response is None:
            return False

        logger.info(
            "gRPC update_labels response: %s",
            MessageToDict(response, preserving_proto_field_name=True),
        )
        if not response.success:
            logger.warning("gRPC update_labels rejected: %s", response.message)
            return False

        logger.info("gRPC update_labels success: %s", response.message)
        return True

    async def create_class_registration(
        self,
        *,
        payload,
    ) -> bool:
        if not self._config.enabled:
            return True

        request_cls = self._requests.get("class_registration_create")
        if request_cls is None:
            logger.warning("Skip gRPC class registration because request class is not ready")
            return False

        items = []
        for item in payload.items:
            items.append(
                {
                    "action": item.action.value,
                    "subjectName": item.subject_name,
                    "subjectCode": item.subject_code,
                    "className": item.class_name,
                    "slotInfo": item.slot_info,
                    "isInCurriculum": item.is_in_curriculum,
                }
            )

        request = request_cls(
            messageId=payload.message_id or 0,
            status=getattr(payload, "status", "") or "",
            studentCode=payload.student_code,
            academicYear=payload.academic_year or 0,
            studentName=payload.student_name,
            note=payload.note or "",
            items=items,
        )
        logger.info(
            "gRPC class registration request: %s",
            MessageToDict(request, preserving_proto_field_name=True),
        )
        response = await self._call(
            service_key="class_registration",
            rpc_name="Create",
            request=request,
        )
        if response is None:
            return False

        logger.info(
            "gRPC class registration response: %s",
            MessageToDict(response, preserving_proto_field_name=True),
        )
        if hasattr(response, "success") and not response.success:
            logger.warning("gRPC class registration rejected: %s", getattr(response, "message", ""))
            return False

        logger.info("gRPC class registration success: %s", getattr(response, "message", ""))
        return True

    async def find_auth_user_by_keyword(self, keyword: str) -> dict | None:
        if not self._config.enabled:
            return None

        request_cls = self._requests.get("auth_find_one_by_keyword")
        if request_cls is None:
            logger.warning("Skip gRPC auth lookup because request class is not ready")
            return None

        request = request_cls(keyword=keyword)
        logger.info(
            "gRPC auth FindOneByKeyword request: %s",
            MessageToDict(request, preserving_proto_field_name=True),
        )
        response = await self._call(
            service_key="auth",
            rpc_name="FindOneByKeyword",
            request=request,
        )
        if response is None:
            return None

        response_dict = MessageToDict(response, preserving_proto_field_name=True)
        logger.info("gRPC auth FindOneByKeyword response: %s", response_dict)
        return response_dict

    async def verify_token(self, token: str) -> dict | None:
        """
        Verify a JWT token via gRPC AuthService.VerifyToken.

        Returns:
            dict — decoded JWT payload (e.g. {sub, email, role, ...}) if valid
            None — if token is invalid/expired or gRPC is unavailable
        """
        if not self._config.enabled:
            logger.debug("gRPC is disabled (GRPC_ENABLED=False). Skipping token verification.")
            return None

        stub_cls = self._stubs.get("auth")
        request_cls = self._requests.get("auth_verify_token")
        if stub_cls is None or request_cls is None:
            logger.warning("Skip gRPC token verify because auth stubs are not ready")
            return None

        target = f"{self._config.host}:{self._config.port}"
        try:
            async with grpc.aio.insecure_channel(target) as channel:
                stub = stub_cls(channel)
                request = request_cls(token=token)
                response = await stub.VerifyToken(request, timeout=self._config.timeout_seconds)
                payload = dict(response.payload)
                logger.debug("gRPC token verified, user: %s", payload.get("email", "unknown"))
                return payload
        except grpc.aio.AioRpcError as exc:
            if exc.code() == grpc.StatusCode.UNAUTHENTICATED:
                logger.info("gRPC token rejected (invalid/expired): %s", exc.details())
            elif exc.code() == grpc.StatusCode.UNAVAILABLE:
                logger.error("gRPC auth server unavailable at %s: %s", target, exc.details())
            elif exc.code() == grpc.StatusCode.DEADLINE_EXCEEDED:
                logger.error(
                    "gRPC token verification timed out after %.1fs", self._config.timeout_seconds
                )
            else:
                logger.warning("gRPC VerifyToken error: %s — %s", exc.code(), exc.details())
            return None
        except Exception as exc:
            logger.warning("gRPC verify_token unexpected error: %s", exc)
            return None

    async def create_task(self, *, payload) -> bool:
        if not self._config.enabled:
            return True

        request_cls = self._requests.get("task_create")
        if request_cls is None:
            logger.warning("Skip gRPC task create because request class is not ready")
            return False

        assignee_ids: list[int] = []
        for item in payload.assignee_ids or []:
            try:
                value = int(item)
            except (TypeError, ValueError):
                logger.warning("Skip non-numeric assignee id: %s", item)
                continue
            if value < -(2**31) or value > 2**31 - 1:
                logger.warning("Skip out-of-range assignee id: %s", value)
                continue
            assignee_ids.append(value)

        priority_value = payload.priority.value if hasattr(payload.priority, "value") else payload.priority
        normalized_priority = priority_value or "medium"
        request = request_cls(
            name=payload.name or "",
            description=payload.description or "",
            due=payload.due or "",
            priority=normalized_priority,
            assigners=list(payload.assigners or []),
            assigneeIds=assignee_ids,
            messageId=int(payload.message_id or 0),
        )
        logger.info(
            "gRPC task create request: %s",
            MessageToDict(
                request,
                preserving_proto_field_name=True,
                including_default_value_fields=True,
            ),
        )
        response = await self._call(
            service_key="task",
            rpc_name="Create",
            request=request,
        )
        if response is None and assignee_ids:
            logger.warning(
                "gRPC task create failed with assigneeIds. Retrying without assigneeIds to avoid proto mismatch.",
            )
            request = request_cls(
                name=payload.name or "",
                description=payload.description or "",
                due=payload.due or "",
                priority=normalized_priority,
                assigners=list(payload.assigners or []),
                assigneeIds=[],
                messageId=int(payload.message_id or 0),
            )
            logger.info(
                "gRPC task create retry request: %s",
                MessageToDict(
                    request,
                    preserving_proto_field_name=True,
                    including_default_value_fields=True,
                ),
            )
            response = await self._call(
                service_key="task",
                rpc_name="Create",
                request=request,
            )
        if response is None:
            return False

        logger.info(
            "gRPC task create response: %s",
            MessageToDict(response, preserving_proto_field_name=True),
        )
        if hasattr(response, "success") and not response.success:
            logger.warning("gRPC task create rejected: %s", getattr(response, "message", ""))
            return False

        logger.info("gRPC task create success: %s", getattr(response, "message", ""))
        return True


# Backward compatibility with old names
GrpcLabelClient = GrpcClient
GrpcLabelClientConfig = GrpcClientConfig


# ---------------------------------------------------------------------------
# Singleton factory — use this for dependency injection (e.g. auth middleware)
# ---------------------------------------------------------------------------

_grpc_client_instance: GrpcClient | None = None


def get_grpc_client() -> GrpcClient:
    """Return the shared GrpcClient singleton, initialised from settings."""
    global _grpc_client_instance
    if _grpc_client_instance is None:
        from app.core.config import settings
        host, port = settings.GRPC_URL.split(":", 1)
        _grpc_client_instance = GrpcClient(
            GrpcClientConfig(
                enabled=settings.GRPC_ENABLED,
                host=host,
                port=int(port),
                timeout_seconds=settings.GRPC_TIMEOUT_SECONDS,
            )
        )
    return _grpc_client_instance


class GrpcInquiryClientAdapter:
    def __init__(self, config: GrpcClientConfig):
        self._client = GrpcInquiryClient(config)

    async def create_inquiry(
        self,
        message_id: int,
        draft_body: str,
        extracted_question: str = None,
        inquiry_types: list[str] = None,
    ) -> bool:
        return await self._client.create_inquiry(
            message_id=message_id,
            draft_body=draft_body,
            extracted_question=extracted_question,
            inquiry_types=inquiry_types,
        )


def get_grpc_inquiry_client() -> GrpcInquiryClientAdapter:
    from app.core.config import settings
    host, port = settings.GRPC_URL.split(":", 1)
    config = GrpcClientConfig(
        enabled=settings.GRPC_ENABLED,
        host=host,
        port=int(port),
        timeout_seconds=settings.GRPC_TIMEOUT_SECONDS,
    )
    return GrpcInquiryClientAdapter(config)

