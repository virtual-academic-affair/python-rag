"""Common gRPC client for external integration calls.

Keep all gRPC methods in this file. Services can call the corresponding
method they need (e.g. update_label, notify_task, create_inquiry).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from importlib import import_module

import grpc
from google.protobuf.json_format import MessageToDict

from app.modules.email.schemas import SystemLabel

logger = logging.getLogger(__name__)


@dataclass
class GrpcClientConfig:
    enabled: bool
    host: str
    port: int
    timeout_seconds: float


class GrpcClient:
    """Shared gRPC client used by multiple services.
    
    This client maintains a single persistent gRPC channel for performance,
    re-using it across all function calls.
    """

    def __init__(self, config: GrpcClientConfig):
        self._config = config
        self._stubs: dict[str, object] = {}
        self._requests: dict[str, object] = {}
        self._channel: grpc.aio.Channel | None = None
        
        if self._config.enabled:
            target = f"{self._config.host}:{self._config.port}"
            self._channel = grpc.aio.insecure_channel(target)
            self._load_stubs()

    async def close(self):
        """Close the underlying gRPC channel."""
        if self._channel:
            await self._channel.close()
            self._channel = None

    def _load_module(self, service_key: str, path_prefix: str, request_map: dict[str, str], stub_class_name: str) -> None:
        """Helper to load a gRPC stub module gracefully."""
        try:
            pb2 = import_module(f"app.proto.{path_prefix}_pb2")
            pb2_grpc = import_module(f"app.proto.{path_prefix}_pb2_grpc")
            
            for req_key, req_class_name in request_map.items():
                self._requests[req_key] = getattr(pb2, req_class_name)
                
            self._stubs[service_key] = getattr(pb2_grpc, stub_class_name)(self._channel)
        except Exception as exc:
            logger.warning(
                "%s gRPC stubs are not available yet. Run proto generation first. Details: %s",
                service_key.capitalize(),
                exc,
            )

    def _load_stubs(self) -> None:
        """Load generated protobuf stubs at runtime and attach them to the channel."""
        self._load_module(
            service_key="message",
            path_prefix="label.label",
            request_map={"update_labels": "UpdateLabelsRequest"},
            stub_class_name="MessageServiceStub"
        )
        
        self._load_module(
            service_key="class_registration",
            path_prefix="class_registration.class_registration",
            request_map={"class_registration_create": "CreateRegistrationRequest"},
            stub_class_name="ClassRegistrationServiceStub"
        )
        
        self._load_module(
            service_key="auth",
            path_prefix="auth.auth",
            request_map={
                "auth_find_one_by_keyword": "FindOneByKeywordRequest",
                "auth_verify_token": "VerifyTokenRequest"
            },
            stub_class_name="AuthServiceStub"
        )
        
        self._load_module(
            service_key="task",
            path_prefix="task.task",
            request_map={"task_create": "CreateTaskRequest"},
            stub_class_name="TaskServiceStub"
        )
        
        self._load_module(
            service_key="inquiry",
            path_prefix="inquiry.inquiry",
            request_map={"inquiry_create": "CreateInquiryRequest"},
            stub_class_name="InquiryServiceStub"
        )

    @property
    def is_ready(self) -> bool:
        return self._config.enabled and bool(self._stubs) and self._channel is not None

    async def _call(self, *, service_key: str, rpc_name: str, request) -> object | None:
        """Centralized RPC executor using the persistent channel."""
        if not self._config.enabled:
            return None
            
        stub = self._stubs.get(service_key)
        if stub is None:
            logger.warning("Skip gRPC call %s because service '%s' is not ready", rpc_name, service_key)
            return None

        try:
            rpc = getattr(stub, rpc_name)
            return await rpc(request, timeout=self._config.timeout_seconds)
        except grpc.aio.AioRpcError as exc:
            if exc.code() == grpc.StatusCode.UNIMPLEMENTED:
                logger.warning(
                    "%s.%s is not yet implemented on nest-api. Skipping.",
                    service_key.capitalize(), rpc_name
                )
            elif exc.code() == grpc.StatusCode.UNAUTHENTICATED:
                logger.info("gRPC call %s unauthenticated/rejected: %s", rpc_name, exc.details())
            elif exc.code() == grpc.StatusCode.UNAVAILABLE:
                logger.error("gRPC server unavailable for %s: %s", rpc_name, exc.details())
            elif exc.code() == grpc.StatusCode.DEADLINE_EXCEEDED:
                logger.error("gRPC call %s timed out after %.1fs", rpc_name, self._config.timeout_seconds)
            else:
                logger.warning("gRPC call %s failed: %s — %s", rpc_name, exc.code(), exc.details())
            
            # Specific handling for verify token which uses these exceptions as expected flow
            if rpc_name == "VerifyToken":
                raise exc
            return None
        except Exception as exc:
            logger.error("gRPC call %s failed: %s", rpc_name, exc, exc_info=True)
            return None

    # =========================================================================
    # Service Endpoints
    # =========================================================================

    async def update_label(
        self,
        *,
        message_id: int,
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

        if message_id is None:
            logger.warning("Skip gRPC label update because message_id is missing")
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
            logger.warning("gRPC update_labels rejected: %s", getattr(response, "message", "No message"))
            return False

        logger.info("gRPC update_labels success: %s", getattr(response, "message", "Ok"))
        return True

    async def create_class_registration(self, *, payload) -> bool:
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

        request_cls = self._requests.get("auth_verify_token")
        if request_cls is None:
            logger.warning("Skip gRPC token verify because auth stubs are not ready")
            return None

        request = request_cls(token=token)
        try:
            response = await self._call(
                service_key="auth",
                rpc_name="VerifyToken",
                request=request
            )
            if response:
                payload = dict(response.payload)
                logger.debug("gRPC token verified, user: %s", payload.get("email", "unknown"))
                return payload
            return None
        except grpc.aio.AioRpcError:
            # Errors already logged in _call method
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
                always_print_fields_with_no_presence=True,
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
                    always_print_fields_with_no_presence=True,
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

    async def create_inquiry(
        self,
        message_id: int,
        answer: str,
        extracted_question: str | None = None,
        inquiry_types: list[str] | None = None,
        sources: list[str] | None = None,
    ) -> bool:
        """Service method: create an inquiry record via gRPC."""
        if not self._config.enabled:
            return True
            
        request_cls = self._requests.get("inquiry_create")
        if request_cls is None:
            logger.warning("Skip gRPC inquiry create because request class is not ready")
            return False

        kwargs = {
            "messageId": message_id,
            "answer": answer,
        }
        if extracted_question is not None:
            kwargs["question"] = extracted_question
        if inquiry_types is not None:
            kwargs["types"] = inquiry_types
        if sources is not None:
            import json
            kwargs["sources"] = [json.dumps(s, ensure_ascii=False) if isinstance(s, dict) else str(s) for s in sources]
            
        request = request_cls(**kwargs)
        response = await self._call(
            service_key="inquiry",
            rpc_name="Create",
            request=request,
        )
        if response is None:
            return False

        if hasattr(response, "success") and not response.success:
            logger.warning("gRPC inquiry create rejected")
            return False
            
        logger.info("Inquiry created via gRPC for messageId=%s", message_id)
        return True


# Backward compatibility bindings
GrpcLabelClient = GrpcClient
GrpcLabelClientConfig = GrpcClientConfig


# ---------------------------------------------------------------------------
# Singleton factory
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

def get_grpc_inquiry_client() -> GrpcClient:
    """Backward compatibility alias."""
    return get_grpc_client()

