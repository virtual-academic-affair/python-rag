"""
MongoDB Database Connection using Motor (async driver).
Provides database instance and connection management.
"""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from typing import Optional, Any
import logging
from pymongo import ASCENDING, DESCENDING

from app.core.config import settings

logger = logging.getLogger(__name__)


class Database:
    """MongoDB database connection manager (Singleton)."""

    # Collection name constants
    FILES = "files"
    FILE_TOC_TREES = "file_toc_trees"
    FAQS = "faqs"
    FAQ_CANDIDATES = "faq_candidates"
    INTERACTION_LOGS = "interaction_logs"
    FORMS = "forms"
    CHAT_SESSIONS = "chat_sessions"
    CHAT_MESSAGES = "chat_messages"

    _client: Optional[Any] = None  # AsyncIOMotorClient
    _db: Optional[Any] = None  # AsyncIOMotorDatabase

    @classmethod
    async def connect(cls):
        """
        Connect to MongoDB.
        Called during FastAPI startup.
        """
        try:
            logger.info(f"Connecting to MongoDB: {settings.MONGODB_DB_NAME}")

            cls._client = AsyncIOMotorClient(
                settings.MONGODB_URL,
                minPoolSize=settings.MONGODB_MIN_POOL_SIZE,
                maxPoolSize=settings.MONGODB_MAX_POOL_SIZE,
                tz_aware=True,          # Return all datetimes as timezone-aware (UTC) instead of naive
                connectTimeoutMS=30000, # Give more margin for Atlas SSL handshake from Docker containers
                serverSelectionTimeoutMS=30000,
            )

            cls._db = cls._client[settings.MONGODB_DB_NAME]

            # Test connection
            await cls._client.admin.command('ping')

            logger.info("✅ MongoDB connected successfully")
        except Exception as e:
            logger.error(f"❌ Failed to connect to MongoDB: {e}")
            raise

    @classmethod
    async def disconnect(cls):
        """
        Disconnect from MongoDB.
        Called during FastAPI shutdown.
        """
        if cls._client:
            cls._client.close()
            logger.info("MongoDB connection closed")

    @classmethod
    def get_db(cls) -> Any:
        """
        Get database instance.

        Returns:
            AsyncIOMotorDatabase instance

        Raises:
            RuntimeError: If database not connected
        """
        if cls._db is None:
            raise RuntimeError("Database not connected. Call Database.connect() first.")
        return cls._db

    @classmethod
    def get_collection(cls, name: str):
        """
        Get a specific collection.

        Args:
            name: Collection name

        Returns:
            AsyncIOMotorCollection
        """
        db = cls.get_db()
        return db[name]


# Convenience function
def get_database() -> Any:
    """Get database instance (AsyncIOMotorDatabase)."""
    return Database.get_db()
