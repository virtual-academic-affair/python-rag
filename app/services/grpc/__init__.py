import logging
from typing import Optional

import grpc
import grpc.aio

from app.proto import email_pb2, email_pb2_grpc

logger = logging.getLogger(__name__)


class GrpcNestEmailClient:

    def __init__(self, grpc_url: str):
        self.grpc_url = grpc_url

    async def create_draft(
        self,
        message_id: int,
        draft_subject: str,
        draft_body: str,
    ) -> bool:
        """
        Call nest-api gRPC EmailService.CreateDraft.
        Returns True on success, False if the method is not yet implemented or on error.
        """
        try:
            async with grpc.aio.insecure_channel(self.grpc_url) as channel:
                stub = email_pb2_grpc.EmailServiceStub(channel)
                request = email_pb2.CreateEmailDraftRequest(
                    messageId=message_id,
                    draftSubject=draft_subject,
                    draftBody=draft_body,
                )
                response = await stub.CreateDraft(request)
                logger.info(f"Gmail draft created via gRPC for messageId={message_id}")
                return response.success
        except grpc.aio.AioRpcError as e:
            if e.code() == grpc.StatusCode.UNIMPLEMENTED:
                logger.warning(
                    f"EmailService.CreateDraft is not yet implemented on nest-api "
                    f"(messageId={message_id}). Skipping."
                )
            else:
                logger.warning(f"gRPC CreateDraft failed: {e.code()} — {e.details()}")
            return False
        except Exception as e:
            logger.warning(f"gRPC CreateDraft unexpected error: {e}")
            return False


_grpc_email_client: Optional[GrpcNestEmailClient] = None


def get_grpc_email_client() -> GrpcNestEmailClient:
    global _grpc_email_client
    if _grpc_email_client is None:
        from app.core.config import settings
        _grpc_email_client = GrpcNestEmailClient(grpc_url=settings.NEST_GRPC_URL)
    return _grpc_email_client
