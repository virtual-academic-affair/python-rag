import logging
from typing import Optional, Dict, Any

import grpc
import grpc.aio

from app.proto.auth import auth_pb2, auth_pb2_grpc

logger = logging.getLogger(__name__)


class GrpcNestAuthClient:

    def __init__(self, grpc_url: str):
        self.grpc_url = grpc_url

    async def verify_token(self, token: str) -> Optional[Dict[str, Any]]:
        try:
            async with grpc.aio.insecure_channel(self.grpc_url) as channel:
                stub = auth_pb2_grpc.AuthServiceStub(channel)
                request = auth_pb2.VerifyTokenRequest(token=token)
                response = await stub.VerifyToken(request)
                payload = dict(response.payload)
                logger.debug(f"Token verified via gRPC, user: {payload.get('email', 'unknown')}")
                return payload

        except grpc.aio.AioRpcError as e:
            logger.warning(f"gRPC token verification RPC error: {e.code()} — {e.details()}")
            return None
        except Exception as e:
            logger.warning(f"gRPC token verification failed: {e}")
            return None


# Singleton instance
_grpc_auth_client: Optional[GrpcNestAuthClient] = None


def get_grpc_auth_client() -> GrpcNestAuthClient:
    """Get or create the gRPC auth client singleton."""
    global _grpc_auth_client
    if _grpc_auth_client is None:
        from app.core.config import settings
        _grpc_auth_client = GrpcNestAuthClient(grpc_url=settings.NEST_GRPC_URL)
    return _grpc_auth_client

