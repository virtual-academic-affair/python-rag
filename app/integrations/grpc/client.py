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
from app.core.exceptions import GrpcServerException
from app.core.config import settings

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
            service_key="inquiry",
            path_prefix="inquiry.inquiry",
            request_map={"inquiry_create": "CreateInquiryRequest"},
            stub_class_name="InquiryServiceStub"
        )

        self._load_module(
            service_key="message",
            path_prefix="message.message",
            request_map={"message_get_state": "GetStateRequest"},
            stub_class_name="MessageServiceStub"
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
            
            # For other RPCs, we still log but now we raise to notify caller
            raise GrpcServerException(f"gRPC call {rpc_name} failed with {exc.code()}: {exc.details()}") from exc
        except Exception as exc:
            if isinstance(exc, GrpcServerException):
                raise
            logger.error("gRPC call %s failed: %s", rpc_name, exc, exc_info=True)
            raise GrpcServerException(f"Internal error during gRPC {rpc_name}: {exc}") from exc

    # =========================================================================
    # Service Endpoints
    # =========================================================================

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
                    "className": item.class_name,
                    "subjectCode": item.subject_code,
                }
            )

        request = request_cls(
            messageId=payload.message_id or 0,
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

    async def create_inquiry(
        self,
        message_id: int,
        answer: str,
        extracted_question: str | None = None,
        inquiry_types: list[str] | None = None,
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

    async def get_message_state(self, message_id: int) -> dict[str, bool] | None:
        """Get message state from MessageService.GetState.

        Returns dict with keys: is_current, has_records; None if unavailable.
        """
        if not self._config.enabled:
            return None

        request_cls = self._requests.get("message_get_state")
        if request_cls is None:
            logger.warning("Skip gRPC message state because request class is not ready")
            return None

        request = request_cls(messageId=message_id)
        response = await self._call(
            service_key="message",
            rpc_name="GetState",
            request=request,
        )
        if response is None:
            return None

        return {
            "is_current": bool(getattr(response, "isCurrent", False)),
            "has_records": bool(getattr(response, "hasRecords", False)),
        }


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

