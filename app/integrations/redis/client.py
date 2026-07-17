import json
import logging
from typing import Any, Optional
from redis.asyncio import Redis, from_url
from pydantic import BaseModel
from app.core.config import settings

logger = logging.getLogger(__name__)


def _json_safe(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


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

    async def mget_json(self, keys: list[str]) -> list[Optional[Any]]:
        """Retrieve JSON values while preserving the input key order."""
        if not keys:
            return []
        if not self._redis:
            return [None] * len(keys)
        try:
            values = await self._redis.mget(keys)
        except Exception as e:
            logger.warning("Failed to MGET %d Redis keys: %s", len(keys), e)
            return [None] * len(keys)

        decoded: list[Optional[Any]] = []
        for key, value in zip(keys, values):
            if value is None:
                decoded.append(None)
                continue
            try:
                decoded.append(json.loads(value))
            except (TypeError, json.JSONDecodeError) as e:
                logger.warning("Invalid JSON in Redis key %s: %s", key, e)
                decoded.append(None)
        return decoded

    async def get_int(self, key: str) -> Optional[int]:
        """Retrieve an integer value from Redis."""
        if not self._redis:
            return None
        try:
            value = await self._redis.get(key)
            return int(value) if value is not None else None
        except Exception as e:
            logger.warning("Failed to get integer key %s from Redis: %s", key, e)
            return None

    async def incr(self, key: str) -> Optional[int]:
        """Increment a Redis counter and return its new value."""
        if not self._redis:
            return None
        try:
            return int(await self._redis.incr(key))
        except Exception as e:
            logger.warning("Failed to increment Redis key %s: %s", key, e)
            return None

    async def set_json(self, key: str, value: Any, ex: Optional[int] = None):
        """Store JSON data in Redis with optional expiry (seconds)."""
        if not self._redis:
            return
        try:
            await self._redis.set(key, json.dumps(_json_safe(value)), ex=ex)
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

    async def delete_many(self, keys: list[str]) -> bool:
        """Delete multiple exact keys without scanning Redis."""
        if not keys:
            return True
        if not self._redis:
            return False
        try:
            await self._redis.delete(*keys)
            return True
        except Exception as e:
            logger.warning("Failed to delete %d Redis keys: %s", len(keys), e)
            return False

_redis_client_instance = None

def get_redis_client() -> RedisClient:
    """Get the singleton Redis client instance."""
    global _redis_client_instance
    if _redis_client_instance is None:
        _redis_client_instance = RedisClient()
    return _redis_client_instance
