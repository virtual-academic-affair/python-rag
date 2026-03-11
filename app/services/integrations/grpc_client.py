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


# Backward compatibility with old names
GrpcLabelClient = GrpcClient
GrpcLabelClientConfig = GrpcClientConfig

