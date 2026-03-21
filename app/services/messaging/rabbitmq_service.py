"""RabbitMQ service for token storage and retrieval"""
import logging
import json
import pika
from typing import Optional, Dict, Any
from app.core.config import settings

logger = logging.getLogger(__name__)


class RabbitMQService:
    """Service for handling token storage and retrieval using RabbitMQ"""

    # Queue names
    TOKEN_QUEUE = "token_storage"

    @property
    def EMAIL_INGEST_QUEUE(self) -> str:
        return settings.RABBITMQ_INGEST_QUEUE

    def __init__(self):
        """Initialize RabbitMQ connection (lazy connection)"""
        self.connection = None
        self.channel = None
        self._connected = False
        self._token_cache = {}  # In-memory cache for tokens

    def _ensure_connection(self):
        """Ensure RabbitMQ connection is established"""
        if self._connected and self.channel and not self.channel.is_closed:
            try:
                # Test connection by declaring queue
                self.channel.queue_declare(queue=self.TOKEN_QUEUE, durable=True)
                return
            except Exception as e:
                logger.warning(f"Connection test failed: {str(e)}")
                self._connected = False
                self.channel = None
                self.connection = None

        try:
            # Create connection
            credentials = pika.PlainCredentials(
                settings.RABBITMQ_USER, settings.RABBITMQ_PASSWORD
            )

            parameters = pika.ConnectionParameters(
                host=settings.RABBITMQ_HOST,
                port=settings.RABBITMQ_PORT,
                virtual_host=settings.RABBITMQ_VHOST,
                credentials=credentials,
                connection_attempts=3,
                retry_delay=2,
                socket_timeout=5,
                heartbeat=60,
            )

            self.connection = pika.BlockingConnection(parameters)
            self.channel = self.connection.channel()

            # Declare queue
            self.channel.queue_declare(queue=self.TOKEN_QUEUE, durable=True)

            self._connected = True
            logger.info(
                f"RabbitMQ connection established: {settings.RABBITMQ_HOST}:{settings.RABBITMQ_PORT}"
            )
        except Exception as e:
            logger.error(f"Failed to connect to RabbitMQ: {str(e)}")
            self._connected = False
            raise

    def store_token(
        self, token_key: str, token_data: Dict[str, Any], ttl: int = 3600
    ) -> bool:
        """Store token data in RabbitMQ."""
        try:
            self._ensure_connection()

            # Store in memory cache with TTL info
            self._token_cache[token_key] = {"data": token_data, "ttl": ttl}

            # Publish to RabbitMQ
            message = json.dumps(
                {"token_key": token_key, "token_data": token_data, "ttl": ttl}
            )

            self.channel.basic_publish(
                exchange="",
                routing_key=self.TOKEN_QUEUE,
                body=message,
                properties=pika.BasicProperties(
                    delivery_mode=pika.spec.PERSISTENT_DELIVERY_MODE,
                    content_type="application/json",
                ),
            )

            logger.info(f"Token stored successfully: {token_key[:20]}...")
            return True
        except Exception as e:
            logger.error(f"Error storing token: {str(e)}")
            return False

    def get_token(self, token_key: str) -> Optional[Dict[str, Any]]:
        """Retrieve token data from cache."""
        try:
            if token_key in self._token_cache:
                return self._token_cache[token_key]["data"]

            logger.warning(f"Token not found in cache: {token_key[:20]}...")
            return None
        except Exception as e:
            logger.error(f"Error retrieving token: {str(e)}")
            return None

    def delete_token(self, token_key: str) -> bool:
        """Delete token from cache."""
        try:
            if token_key in self._token_cache:
                del self._token_cache[token_key]
                logger.info(f"Token deleted: {token_key[:20]}...")
                return True
            return False
        except Exception as e:
            logger.error(f"Error deleting token: {str(e)}")
            return False

    def close(self):
        """Close RabbitMQ connection"""
        try:
            if self.connection and not self.connection.is_closed:
                self.connection.close()
                self._connected = False
                logger.info("RabbitMQ connection closed")
        except Exception as e:
            logger.error(f"Error closing RabbitMQ connection: {str(e)}")

    def declare_email_ingest_queue(self):
        """Ensure the email ingest queue exists."""
        self._ensure_connection()
        self.channel.queue_declare(queue=self.EMAIL_INGEST_QUEUE, durable=True)

    def start_email_ingest_consumer(self, on_message_callback, prefetch_count: int = 10):
        """Start consuming messages from the email ingest queue.

        This is a blocking call. Run it in a dedicated thread/process.
        """
        self._ensure_connection()
        self.channel.queue_declare(queue=self.EMAIL_INGEST_QUEUE, durable=True)
        self.channel.basic_qos(prefetch_count=prefetch_count)
        self.channel.basic_consume(
            queue=self.EMAIL_INGEST_QUEUE,
            on_message_callback=on_message_callback,
            auto_ack=False,
        )
        logger.info(f"Starting consumer on queue: {self.EMAIL_INGEST_QUEUE}")
        self.channel.start_consuming()


_rabbitmq_service: Optional[RabbitMQService] = None


def get_rabbitmq_service() -> RabbitMQService:
    """Get or create RabbitMQ service instance"""
    global _rabbitmq_service
    if _rabbitmq_service is None:
        _rabbitmq_service = RabbitMQService()
    return _rabbitmq_service

