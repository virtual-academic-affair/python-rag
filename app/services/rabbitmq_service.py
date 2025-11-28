"""RabbitMQ service for token storage and retrieval"""
import logging
import json
import pika
from typing import Optional, Dict, Any
from config.settings import settings

logger = logging.getLogger(__name__)


class RabbitMQService:
    """Service for handling token storage and retrieval using RabbitMQ"""
    
    # Queue names
    TOKEN_QUEUE = "token_storage"
    
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
                settings.RABBITMQ_USER,
                settings.RABBITMQ_PASSWORD
            )
            
            parameters = pika.ConnectionParameters(
                host=settings.RABBITMQ_HOST,
                port=settings.RABBITMQ_PORT,
                virtual_host=settings.RABBITMQ_VHOST,
                credentials=credentials,
                connection_attempts=3,
                retry_delay=2,
                socket_timeout=5
            )
            
            self.connection = pika.BlockingConnection(parameters)
            self.channel = self.connection.channel()
            
            # Declare queue
            self.channel.queue_declare(queue=self.TOKEN_QUEUE, durable=True)
            
            self._connected = True
            logger.info(f"RabbitMQ connection established: {settings.RABBITMQ_HOST}:{settings.RABBITMQ_PORT}")
        except Exception as e:
            logger.error(f"Failed to connect to RabbitMQ: {str(e)}")
            self._connected = False
            raise
    
    def store_token(self, token_key: str, token_data: Dict[str, Any], ttl: int = 3600) -> bool:
        """
        Store token data in RabbitMQ.
        
        Args:
            token_key: Key to identify the token
            token_data: Token data to store
            ttl: Time to live in seconds (default: 1 hour)
            
        Returns:
            True if stored successfully, False otherwise
        """
        try:
            self._ensure_connection()
            
            # Store in memory cache with TTL info
            self._token_cache[token_key] = {
                "data": token_data,
                "ttl": ttl
            }
            
            # Publish to RabbitMQ
            message = json.dumps({
                "token_key": token_key,
                "token_data": token_data,
                "ttl": ttl
            })
            
            self.channel.basic_publish(
                exchange='',
                routing_key=self.TOKEN_QUEUE,
                body=message,
                properties=pika.BasicProperties(
                    delivery_mode=pika.spec.PERSISTENT_DELIVERY_MODE,
                    content_type='application/json'
                )
            )
            
            logger.info(f"Token stored successfully: {token_key[:20]}...")
            return True
        except Exception as e:
            logger.error(f"Error storing token: {str(e)}")
            return False
    
    def get_token(self, token_key: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve token data from cache or RabbitMQ.
        
        Args:
            token_key: Key to look up
            
        Returns:
            Token data if found, None otherwise
        """
        try:
            # Check in-memory cache first
            if token_key in self._token_cache:
                return self._token_cache[token_key]["data"]
            
            # If not in cache, try to retrieve from RabbitMQ
            # Note: RabbitMQ is not ideal for retrieval, so we rely on cache
            # In production, you might want to use a persistent store alongside RabbitMQ
            logger.warning(f"Token not found in cache: {token_key[:20]}...")
            return None
        except Exception as e:
            logger.error(f"Error retrieving token: {str(e)}")
            return None
    
    def delete_token(self, token_key: str) -> bool:
        """
        Delete token from cache.
        
        Args:
            token_key: Key to delete
            
        Returns:
            True if deleted, False otherwise
        """
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


# Global RabbitMQ service instance
_rabbitmq_service: Optional[RabbitMQService] = None


def get_rabbitmq_service() -> RabbitMQService:
    """Get or create RabbitMQ service instance"""
    global _rabbitmq_service
    if _rabbitmq_service is None:
        _rabbitmq_service = RabbitMQService()
    return _rabbitmq_service

