from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from pymongo import ASCENDING, DESCENDING, ReturnDocument

from app.core.database import Database


class ChatHistoryRepository:
    """MongoDB repository for chat sessions and messages."""

    SESSION_STATUS_ACTIVE = "active"
    SESSION_STATUS_ARCHIVED = "archived"

    def __init__(self) -> None:
        self._sessions = Database.get_collection(Database.CHAT_SESSIONS)
        self._messages = Database.get_collection(Database.CHAT_MESSAGES)

    async def ensure_session(self, session_id: str, user_id: str) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        session = await self._sessions.find_one_and_update(
            {"session_id": session_id, "user_id": user_id},
            {
                "$set": {
                    "updated_at": now,
                    "last_message_at": now,
                    "status": self.SESSION_STATUS_ACTIVE,
                },
                "$setOnInsert": {
                    "session_id": session_id,
                    "user_id": user_id,
                    "title": None,
                    "metadata": {},
                    "message_count": 0,
                    "created_at": now,
                },
            },
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        return session or {}

    async def append_message(
        self,
        session_id: str,
        user_id: str,
        role: str,
        content: str,
        token_usage: Optional[dict[str, Any]] = None,
        sources: Optional[list[dict[str, Any]]] = None,
        processing_time_ms: Optional[int] = None,
        message_type: str = "text",
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        session = await self._sessions.find_one_and_update(
            {"session_id": session_id, "user_id": user_id},
            {
                "$inc": {"message_count": 1},
                "$set": {
                    "updated_at": now,
                    "last_message_at": now,
                },
                "$setOnInsert": {
                    "session_id": session_id,
                    "user_id": user_id,
                    "title": None,
                    "metadata": {},
                    "status": self.SESSION_STATUS_ACTIVE,
                    "created_at": now,
                },
            },
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        sequence = int((session or {}).get("message_count", 1))

        if role == "user" and sequence == 1:
            await self._sessions.update_one(
                {
                    "session_id": session_id,
                    "user_id": user_id,
                    "title": None,
                },
                {
                    "$set": {
                        "title": content,
                        "updated_at": now,
                    }
                },
            )

        message_doc = {
            "session_id": session_id,
            "user_id": user_id,
            "role": role,
            "content": content,
            "message_type": message_type,
            "token_usage": token_usage,
            "sources": sources or [],
            "processing_time_ms": processing_time_ms,
            "sequence": sequence,
            "created_at": now,
        }
        result = await self._messages.insert_one(message_doc)
        message_doc["_id"] = str(result.inserted_id)
        return message_doc

    async def list_sessions_by_user(
        self,
        user_id: str,
        limit: int,
        skip: int,
        status: Optional[str] = None,
    ) -> tuple[list[dict[str, Any]], int]:
        query: dict[str, Any] = {"user_id": user_id}
        if status:
            query["status"] = status

        total = await self._sessions.count_documents(query)
        cursor = self._sessions.find(query).sort("last_message_at", DESCENDING).skip(skip).limit(limit)
        sessions = await cursor.to_list(length=limit)
        return sessions, total

    async def list_messages_by_session(
        self,
        session_id: str,
        user_id: str,
        limit: int,
        skip: int,
    ) -> tuple[list[dict[str, Any]], int]:
        query = {"session_id": session_id, "user_id": user_id}
        total = await self._messages.count_documents(query)
        cursor = self._messages.find(query).sort("sequence", ASCENDING).skip(skip).limit(limit)
        messages = await cursor.to_list(length=limit)
        return messages, total

    async def rename_session(self, session_id: str, user_id: str, title: str) -> bool:
        now = datetime.now(timezone.utc)
        result = await self._sessions.update_one(
            {"session_id": session_id, "user_id": user_id},
            {"$set": {"title": title, "updated_at": now}},
        )
        return result.matched_count > 0

    async def archive_session(self, session_id: str, user_id: str) -> bool:
        now = datetime.now(timezone.utc)
        result = await self._sessions.update_one(
            {"session_id": session_id, "user_id": user_id},
            {"$set": {"status": self.SESSION_STATUS_ARCHIVED, "updated_at": now}},
        )
        return result.matched_count > 0

    async def unarchive_session(self, session_id: str, user_id: str) -> bool:
        now = datetime.now(timezone.utc)
        result = await self._sessions.update_one(
            {"session_id": session_id, "user_id": user_id},
            {"$set": {"status": self.SESSION_STATUS_ACTIVE, "updated_at": now}},
        )
        return result.matched_count > 0

    async def delete_session(self, session_id: str, user_id: str) -> bool:
        delete_session_result = await self._sessions.delete_one({"session_id": session_id, "user_id": user_id})
        await self._messages.delete_many({"session_id": session_id, "user_id": user_id})
        return delete_session_result.deleted_count > 0


_chat_history_repo: Optional[ChatHistoryRepository] = None


def get_chat_history_repository() -> ChatHistoryRepository:
    global _chat_history_repo
    if _chat_history_repo is None:
        _chat_history_repo = ChatHistoryRepository()
    return _chat_history_repo

