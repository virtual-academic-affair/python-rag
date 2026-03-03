import asyncio
import json
import logging
import threading
from typing import Any, Dict, Optional

from app.models.schemas import InternalData, IngestMessage
from app.services.messaging.rabbitmq_service import get_rabbitmq_service

logger = logging.getLogger(__name__)


def _safe_json_loads(body: bytes) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(body.decode("utf-8"))
    except Exception:
        return None


def _build_internal_data(payload: Dict[str, Any]) -> InternalData:
    data = payload.get("data") or {}
    email_id = data.get("emailId")
    return InternalData(
        mail_id=str(email_id) if email_id is not None else "",
        id_record=str(email_id) if email_id is not None else "",
    )


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

        email_id = msg.data.email_id
        title = msg.data.subject
        content = msg.data.content

        internal = InternalData(mail_id=str(email_id), id_record=str(email_id))

        logger.info(
            "Parsed ingest message: emailId=%s senderEmail=%s senderName=%s subject=%r content_len=%s",
            email_id,
            msg.data.sender_email,
            msg.data.sender_name,
            title,
            len(content),
        )
        logger.info(
            "LLM input -> internal=%s title=%r content_preview=%r",
            internal.model_dump(),
            title,
            content[:500],
        )

        async def _handle():
            return await classifier.process_request(
                internal_data=internal,
                title=title,
                content=content,
            )

        try:
            fut = asyncio.run_coroutine_threadsafe(_handle(), loop)
            result = fut.result(timeout=120)
            logger.info(
                "Email ingested processed: emailId=%s label=%s",
                email_id,
                getattr(result, "label", None),
            )
            ch.basic_ack(delivery_tag=method.delivery_tag)
        except Exception as e:
            logger.error("Failed processing ingest message: %s", str(e), exc_info=True)
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)

    def _run():
        try:
            rabbitmq_service.start_email_ingest_consumer(on_message_callback=on_message)
        except Exception as e:
            logger.error("Email ingest consumer crashed: %s", str(e), exc_info=True)

    t = threading.Thread(target=_run, name="email-ingest-consumer", daemon=True)
    t.start()
    return t

