import json
import logging
from typing import Any, Optional
from redis.asyncio import Redis, from_url
from app.core.config import settings

logger = logging.getLogger(__name__)

class RedisClient:
    """
    Async Redis client for shared caching.
    """
    def __init__(self):
        self._redis: Optional[Redis] = None

    async def connect(self):
        """Initialize connection to Redis."""
        if not settings.REDIS_ENABLED:
            logger.warning("Redis is disabled in settings.")
            return
        if self._redis is None:
            try:
                self._redis = from_url(
                    settings.REDIS_URL,
                    decode_responses=True,
                    socket_timeout=settings.REDIS_TIMEOUT,
                    socket_keepalive=True,
                    health_check_interval=60,
                    ssl_cert_reqs=None,
                )
                # Test connection
                await self._redis.ping()
                logger.info("✅ Connected to Redis at %s", settings.REDIS_URL)
            except Exception as e:
                logger.error("❌ Failed to connect to Redis: %s", e)
                self._redis = None

    async def disconnect(self):
        """Close Redis connection."""
        if self._redis:
            await self._redis.close()
            self._redis = None
            logger.info("Redis connection closed.")

    async def get_json(self, key: str) -> Optional[Any]:
        """Retrieve JSON data from Redis."""
        if not self._redis:
            return None
        try:
            data = await self._redis.get(key)
            return json.loads(data) if data else None
        except Exception as e:
            logger.warning("Failed to get key %s from Redis: %s", key, e)
            return None

    async def set_json(self, key: str, value: Any, ex: Optional[int] = None):
        """Store JSON data in Redis with optional expiry (seconds)."""
        if not self._redis:
            return
        try:
            await self._redis.set(key, json.dumps(value), ex=ex)
        except Exception as e:
            logger.warning("Failed to set key %s in Redis: %s", key, e)

    async def delete(self, key: str):
        """Delete a key from Redis."""
        if not self._redis:
            return
        try:
            await self._redis.delete(key)
        except Exception as e:
            logger.warning("Failed to delete key %s from Redis: %s", key, e)

_redis_client_instance = None

def get_redis_client() -> RedisClient:
    """Get the singleton Redis client instance."""
    global _redis_client_instance
    if _redis_client_instance is None:
        _redis_client_instance = RedisClient()
    return _redis_client_instance
