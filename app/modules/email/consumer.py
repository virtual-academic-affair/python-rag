import asyncio
import json
import logging
import time
import threading
from typing import Any, Dict, Optional

import pika
import pika.exceptions

from app.core.config import settings
from app.modules.email.exceptions import (
    DownstreamCommitError,
    PermanentEmailError,
    RetryableEmailError,
)
from app.modules.email.models.email_types import IngestMessage
from app.integrations.rabbitmq.client import get_rabbitmq_service
from app.integrations.grpc.client import get_grpc_client
from app.modules.email.utils.notifier import (
    EMAIL_INGEST_PROGRESS_CHANNEL,
    get_email_status_notifier,
)

logger = logging.getLogger(__name__)


def _safe_json_loads(body: bytes) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(body.decode("utf-8"))
    except Exception:
        return None


def _get_message_id(payload: Dict[str, Any]) -> Optional[int]:
    data = payload.get("data") or {}
    message_id = data.get("messageId")
    return message_id if isinstance(message_id, int) else None


def _safe_ack(ch, delivery_tag: int) -> None:
    """Acknowledge a message, ignoring errors if the channel is already closed."""
    try:
        ch.basic_ack(delivery_tag=delivery_tag)
    except (pika.exceptions.ChannelWrongStateError, pika.exceptions.AMQPConnectionError) as e:
        logger.warning("Could not ack message (channel/connection closed): %s", e)
    except Exception as e:
        logger.warning("Unexpected error during basic_ack: %s", e)


def _safe_nack(ch, delivery_tag: int, requeue: bool = False) -> None:
    """Nack a message, ignoring errors if the channel is already closed."""
    try:
        ch.basic_nack(delivery_tag=delivery_tag, requeue=requeue)
    except (pika.exceptions.ChannelWrongStateError, pika.exceptions.AMQPConnectionError) as e:
        logger.warning("Could not nack message (channel/connection closed): %s", e)
    except Exception as e:
        logger.warning("Unexpected error during basic_nack: %s", e)


def _get_retry_count(properties) -> int:
    """Read the custom x-retry-count header to determine how many times this message has
    been re-published by us for retry.
    """
    try:
        headers = getattr(properties, "headers", None) or {}
        return int(headers.get("x-retry-count", 0))
    except Exception:
        pass
    return 0


def _clone_properties_with_retry_count(properties, next_retry_count: int):
    headers = getattr(properties, "headers", None) or {}
    new_headers = dict(headers)
    new_headers["x-retry-count"] = next_retry_count
    return pika.BasicProperties(
        content_type=getattr(properties, 'content_type', None),
        content_encoding=getattr(properties, 'content_encoding', None),
        priority=getattr(properties, 'priority', None),
        correlation_id=getattr(properties, 'correlation_id', None),
        reply_to=getattr(properties, 'reply_to', None),
        expiration=getattr(properties, 'expiration', None),
        message_id=getattr(properties, 'message_id', None),
        timestamp=getattr(properties, 'timestamp', None),
        type=getattr(properties, 'type', None),
        user_id=getattr(properties, 'user_id', None),
        app_id=getattr(properties, 'app_id', None),
        cluster_id=getattr(properties, 'cluster_id', None),
        delivery_mode=getattr(properties, 'delivery_mode', None),
        headers=new_headers,
    )


def start_email_ingest_consumer(
    classifier,
    *,
    loop: asyncio.AbstractEventLoop,
) -> threading.Thread:
    rabbitmq_service = get_rabbitmq_service()

    def on_message(ch, method, properties, body):
        logger.info(
            "RabbitMQ received message: delivery_tag=%s bytes=%s",
            getattr(method, "delivery_tag", None),
            len(body) if body is not None else 0,
        )

        payload = _safe_json_loads(body)
        if not payload:
            preview = body[:500].decode("utf-8", errors="replace") if body else ""
            logger.warning(
                "Invalid JSON payload; preview=%r; acking to avoid poison loop",
                preview,
            )
            ch.basic_ack(delivery_tag=method.delivery_tag)
            return

        logger.info("RabbitMQ payload: %s", json.dumps(payload, ensure_ascii=False))

        try:
            msg = IngestMessage.model_validate(payload)
        except Exception as e:
            logger.warning("Invalid ingest message schema: %s", str(e), exc_info=True)
            ch.basic_ack(delivery_tag=method.delivery_tag)
            return

        message_id = msg.data.message_id
        thread_id = msg.data.thread_id
        title = msg.data.subject
        content = msg.data.content

        logger.info(
            "Parsed ingest message: messageId=%s threadId=%s senderEmail=%s senderName=%s subject=%r content_len=%s",
            message_id,
            thread_id,
            msg.data.sender_email,
            msg.data.sender_name,
            title,
            len(content),
        )

        async def _check_message_state() -> bool:
            """Return True if message should be processed, False if it should be skipped.
            Raises RetryableEmailError if state is temporarily unavailable.
            """
            if not settings.GRPC_ENABLED:
                # gRPC disabled (dev/test): skip state check, always process.
                return True
            grpc_client = get_grpc_client()
            try:
                state = await grpc_client.get_message_state(message_id)
            except Exception as exc:
                raise RetryableEmailError(
                    f"GetState gRPC call failed for messageId={message_id}: {exc}"
                ) from exc

            if state is None:
                # Stub not loaded yet — treat as transient unavailable.
                raise RetryableEmailError(
                    f"GetState returned None for messageId={message_id} (stub not ready)"
                )

            is_current = state["is_current"]
            has_records = state["has_records"]
            should_process = is_current and (not has_records)
            if not should_process:
                logger.info(
                    "Skip stale/deleted/processed messageId=%s (is_current=%s has_records=%s)",
                    message_id,
                    is_current,
                    has_records,
                )
            return should_process

        async def _emit_status_event(event_name: str, stage: str, reason: Optional[str] = None) -> None:
            payload = {
                "event": event_name,
                "messageId": message_id,
                "threadId": thread_id,
                "stage": stage,
            }
            if reason:
                payload["reason"] = reason
            notifier = get_email_status_notifier()
            targets = {EMAIL_INGEST_PROGRESS_CHANNEL}
            if thread_id:
                targets.add(thread_id)
            for target in targets:
                await notifier.notify(target, payload)

        async def _handle():
            if not await _check_message_state():
                await _emit_status_event(
                    event_name="email_processing_skipped",
                    stage="skipped",
                    reason="message_state_not_processable",
                )
                return None

            await _emit_status_event(
                event_name="email_processing_started",
                stage="processing",
            )
            logger.info(
                "LLM input -> messageId=%s title=%r content_preview=%r",
                message_id,
                title,
                content[:500],
            )
            result = await classifier.process_request(
                message_id=message_id,
                title=title,
                content=content,
                sender_email=msg.data.sender_email,
                sender_name=msg.data.sender_name,
                student_code=msg.data.student_code,
                enrollment_year=msg.data.enrollment_year,
                raise_on_grpc_fail=True,
            )
            await _emit_status_event(
                event_name="email_processing_done",
                stage="done",
            )
            return result

        try:
            fut = asyncio.run_coroutine_threadsafe(_handle(), loop)
            result = fut.result(timeout=300)
            if result is None:
                logger.info("Email ingest ignored (skipped): messageId=%s", message_id)
                _safe_ack(ch, method.delivery_tag)
                return

            logger.info(
                "Email ingest processed: messageId=%s label=%s",
                message_id,
                getattr(result, "label", None) or getattr(result, "labels", None),
            )
            _safe_ack(ch, method.delivery_tag)

        except (RetryableEmailError, DownstreamCommitError) as e:
            retry_count = _get_retry_count(properties)
            logger.warning(
                "Retryable error for messageId=%s (retry_count=%d/%d): %s",
                message_id,
                retry_count,
                settings.RABBITMQ_EMAIL_MAX_RETRIES,
                e,
            )
            try:
                asyncio.run_coroutine_threadsafe(
                    _emit_status_event("email_processing_failed", "failed", reason=str(e)),
                    loop,
                ).result(timeout=10)
            except Exception:
                pass

            if retry_count < settings.RABBITMQ_EMAIL_MAX_RETRIES:
                # Manually re-publish with incremented retry count in custom header.
                try:
                    new_properties = _clone_properties_with_retry_count(properties, retry_count + 1)
                    rabbitmq_service.publish_to_main_queue(body, new_properties)
                    _safe_ack(ch, method.delivery_tag)
                    logger.info(
                        "Re-published messageId=%s for retry (%d/%d)",
                        message_id,
                        retry_count + 1,
                        settings.RABBITMQ_EMAIL_MAX_RETRIES,
                    )
                except Exception as pub_err:
                    logger.error("Failed to re-publish for retry: %s", pub_err)
                    _safe_nack(ch, method.delivery_tag, requeue=True)
            else:
                logger.error(
                    "messageId=%s exhausted %d retries — routing to DLQ",
                    message_id,
                    settings.RABBITMQ_EMAIL_MAX_RETRIES,
                )
                _safe_nack(ch, method.delivery_tag, requeue=False)  # → DLQ via DLX

        except PermanentEmailError as e:
            logger.error(
                "Permanent error for messageId=%s — routing to DLQ immediately: %s",
                message_id,
                e,
            )
            try:
                asyncio.run_coroutine_threadsafe(
                    _emit_status_event("email_processing_failed", "failed", reason=str(e)),
                    loop,
                ).result(timeout=10)
            except Exception:
                pass
            _safe_nack(ch, method.delivery_tag, requeue=False)  # → DLQ via DLX

        except Exception as e:
            logger.error(
                "Unexpected error for messageId=%s — routing to DLQ: %s",
                message_id,
                e,
                exc_info=True,
            )
            try:
                asyncio.run_coroutine_threadsafe(
                    _emit_status_event("email_processing_failed", "failed", reason="unexpected_error"),
                    loop,
                ).result(timeout=10)
            except Exception:
                pass
            _safe_nack(ch, method.delivery_tag, requeue=False)  # → DLQ



    def _run():
        max_retries = 10
        retry_delay = 5
        for attempt in range(1, max_retries + 1):
            try:
                logger.info("Email ingest consumer starting (attempt %d/%d)", attempt, max_retries)
                rabbitmq_service.start_email_ingest_consumer(on_message_callback=on_message)
            except Exception as e:
                logger.error(
                    "Email ingest consumer crashed (attempt %d/%d): %s",
                    attempt, max_retries, str(e), exc_info=True,
                )
                if attempt < max_retries:
                    sleep_sec = min(retry_delay * attempt, 60)
                    logger.info("Reconnecting in %ds...", sleep_sec)
                    time.sleep(sleep_sec)
                else:
                    logger.error("Email ingest consumer exhausted all retries, giving up.")

    t = threading.Thread(target=_run, name="email-ingest-consumer", daemon=True)
    t.start()
    return t
