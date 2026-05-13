import asyncio
import json
import logging
import time
import threading
from typing import Any, Dict, Optional

from app.modules.email.schemas import IngestMessage
from app.integrations.rabbitmq.client import get_rabbitmq_service
from app.integrations.grpc.client import get_grpc_client
from app.modules.email.notifier import (
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


def start_email_ingest_consumer(
    classifier,
    *,
    loop: asyncio.AbstractEventLoop,
) -> threading.Thread:
    rabbitmq_service = get_rabbitmq_service()
    rabbitmq_service.declare_email_ingest_queue()

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
        title = msg.data.subject
        content = msg.data.content

        logger.info(
            "Parsed ingest message: messageId=%s senderEmail=%s senderName=%s subject=%r content_len=%s",
            message_id,
            msg.data.sender_email,
            msg.data.sender_name,
            title,
            len(content),
        )

        async def _check_message_state() -> bool:
            grpc_client = get_grpc_client()
            state = await grpc_client.get_message_state(message_id)
            if state is None:
                logger.warning(
                    "Cannot fetch MessageService.GetState for messageId=%s; skip processing this message",
                    message_id,
                )
                return False

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

        async def _emit_processing_started_event() -> None:
            payload = {
                "event": "email_processing_started",
                "messageId": message_id,
                "stage": "processing",
            }
            notifier = get_email_status_notifier()
            await notifier.notify(EMAIL_INGEST_PROGRESS_CHANNEL, payload)

        async def _handle():
            if not await _check_message_state():
                return None

            await _emit_processing_started_event()
            logger.info(
                "LLM input -> messageId=%s title=%r content_preview=%r",
                message_id,
                title,
                content[:500],
            )
            return await classifier.process_request(
                message_id=message_id,
                title=title,
                content=content,
                sender_email=msg.data.sender_email,
                sender_name=msg.data.sender_name,
            )

        try:
            fut = asyncio.run_coroutine_threadsafe(_handle(), loop)
            result = fut.result(timeout=120)
            if result is None:
                logger.info("Email ingest ignored: messageId=%s", message_id)
                ch.basic_ack(delivery_tag=method.delivery_tag)
                return

            logger.info(
                "Email ingested processed: messageId=%s label=%s",
                message_id,
                getattr(result, "label", None),
            )
            ch.basic_ack(delivery_tag=method.delivery_tag)
        except Exception as e:
            logger.error("Failed processing ingest message: %s", str(e), exc_info=True)
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)

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

