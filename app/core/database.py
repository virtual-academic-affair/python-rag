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
        if settings.MONGODB_DISABLED:
            logger.warning("⚠️  MongoDB is disabled via settings. Skipping connection.")
            cls._client = None
            cls._db = None
            return
        try:
            logger.info(f"Connecting to MongoDB: {settings.MONGODB_DB_NAME}")

            cls._client = AsyncIOMotorClient(
                settings.MONGODB_URL,
                minPoolSize=settings.MONGODB_MIN_POOL_SIZE,
                maxPoolSize=settings.MONGODB_MAX_POOL_SIZE,
                tz_aware=True,  # Return all datetimes as timezone-aware (UTC) instead of naive
            )

            cls._db = cls._client[settings.MONGODB_DB_NAME]

            # Test connection
            await cls._client.admin.command('ping')

            logger.info("✅ MongoDB connected successfully")

            # Ensure indexes
            file_toc_trees = cls._db[cls.FILE_TOC_TREES]
            await file_toc_trees.create_index([("file_id", ASCENDING)], name="idx_file_toc_trees_file_id", unique=True)

            files_col = cls._db[cls.FILES]

            indexes_to_create = [
                ([("display_name_unaccented", ASCENDING)], "idx_files_display_name"),
                ([("status", ASCENDING)], "status_1"),
            ]

            for keys, name in indexes_to_create:
                try:
                    await files_col.create_index(keys, name=name)
                except Exception as e:
                    # Ignore index name conflict if it already exists, log others
                    if getattr(e, 'code', None) == 85:
                        pass
                    else:
                        logger.warning(f"⚠️ Could not create index {name}: {e}")

            # Ensure FAQ indexes
            interaction_col = cls._db[cls.INTERACTION_LOGS]
            await interaction_col.create_index(
                [("expires_at", ASCENDING)],
                expireAfterSeconds=0,
                name="idx_interaction_logs_ttl"
            )
            await interaction_col.create_index(
                [("question_unaccented", ASCENDING), ("expires_at", ASCENDING)],
                name="idx_interaction_logs_dedup"
            )
            await interaction_col.create_index(
                [("source_type", ASCENDING), ("expires_at", ASCENDING)],
                name="idx_interaction_logs_source"
            )

            faqs_col = cls._db[cls.FAQS]
            await faqs_col.create_index([("is_active", ASCENDING), ("sort_order", ASCENDING)], name="idx_faqs_active")
            await faqs_col.create_index([("question_unaccented", "text"), ("answer_unaccented", "text")], name="idx_faqs_text")

            cands_col = cls._db[cls.FAQ_CANDIDATES]
            await cands_col.create_index([("status", ASCENDING), ("created_at", ASCENDING)], name="idx_faq_cands_status")

            # Ensure Chat history indexes
            sessions_col = cls._db[cls.CHAT_SESSIONS]
            await sessions_col.create_index([("session_id", ASCENDING)], name="idx_chat_sessions_session_id", unique=True)
            await sessions_col.create_index([("user_id", ASCENDING), ("last_message_at", DESCENDING)], name="idx_chat_sessions_user_last_message")
            await sessions_col.create_index([("user_id", ASCENDING), ("status", ASCENDING), ("updated_at", DESCENDING)], name="idx_chat_sessions_user_status_updated")

            messages_col = cls._db[cls.CHAT_MESSAGES]
            await messages_col.create_index([("session_id", ASCENDING), ("sequence", ASCENDING)], name="idx_chat_messages_session_sequence")
            await messages_col.create_index([("user_id", ASCENDING), ("created_at", DESCENDING)], name="idx_chat_messages_user_created")
            await messages_col.create_index([("session_id", ASCENDING), ("created_at", ASCENDING)], name="idx_chat_messages_session_created")
            await cands_col.create_index([("question_unaccented", "text"), ("answer_draft_unaccented", "text")], name="idx_faq_cands_text")

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
