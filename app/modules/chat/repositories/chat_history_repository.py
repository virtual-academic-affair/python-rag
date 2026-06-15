from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional, Dict

from app.modules.chat.models.chat_session import ChatSessionDocument
from app.modules.chat.models.chat_message import ChatMessageDocument

# Single source of truth for which pipeline step types are persisted to MongoDB.
PERSISTED_STEP_TYPES = frozenset({"query_analysis", "faq_check", "retrieval", "call"})


class ChatHistoryRepository:
    """MongoDB repository for chat sessions and messages using Beanie ODM."""

    SESSION_STATUS_ACTIVE = "active"
    SESSION_STATUS_ARCHIVED = "archived"

    def _serialize_doc(self, doc) -> Optional[Dict[str, Any]]:
        if not doc:
            return None
        if isinstance(doc, dict):
            d = doc.copy()
            if "_id" in d:
                d["_id"] = str(d["_id"])
            return d
        d = doc.model_dump(by_alias=True)
        d["_id"] = str(doc.id)
        return d

    async def ensure_session(self, session_id: str, user_id: str) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        session = await ChatSessionDocument.find_one(
            ChatSessionDocument.session_id == session_id,
            ChatSessionDocument.user_id == user_id
        )
        if not session:
            session = ChatSessionDocument(
                session_id=session_id,
                user_id=user_id,
                title=None,
                metadata={},
                message_count=0,
                status=self.SESSION_STATUS_ACTIVE,
                last_message_at=now,
            )
            await session.insert()
        else:
            session.updated_at = now
            session.last_message_at = now
            session.status = self.SESSION_STATUS_ACTIVE
            await session.save()
            
        return self._serialize_doc(session)

    async def append_message(
        self,
        session_id: str,
        user_id: str,
        role: str,
        content: str,
        token_usage: Optional[dict[str, Any]] = None,
        sources: Optional[list[dict[str, Any]]] = None,
        steps: Optional[list[dict[str, Any]]] = None,
        processing_time_ms: Optional[int] = None,
        message_type: str = "text",
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        session = await ChatSessionDocument.find_one(
            ChatSessionDocument.session_id == session_id,
            ChatSessionDocument.user_id == user_id
        )
        if not session:
            session = ChatSessionDocument(
                session_id=session_id,
                user_id=user_id,
                title=None,
                metadata={},
                message_count=1,
                status=self.SESSION_STATUS_ACTIVE,
                last_message_at=now,
            )
            await session.insert()
        else:
            session.message_count += 1
            session.updated_at = now
            session.last_message_at = now
            await session.save()
            
        sequence = session.message_count

        if role == "user" and sequence == 1:
            if not session.title:
                session.title = content
                await session.save()

        # Enforce the persistence whitelist
        persisted_steps = [
            s
            for s in (steps or [])
            if isinstance(s, dict) and s.get("type") in PERSISTED_STEP_TYPES
        ]

        message_doc = ChatMessageDocument(
            session_id=session_id,
            user_id=user_id,
            role=role,
            content=content,
            message_type=message_type,
            token_usage=token_usage,
            sources=sources or [],
            steps=persisted_steps,
            processing_time_ms=processing_time_ms,
            sequence=sequence,
        )
        await message_doc.insert()
        return self._serialize_doc(message_doc)

    async def get_recent_messages(
        self,
        session_id: str,
        user_id: str,
        limit: int = 6,
        message_type: str = "text",
    ) -> list[dict[str, Any]]:
        """
        Lấy (limit) tin nhắn cuối cùng của session, chỉ lấy message_type='text'.
        Trả về danh sách dict theo thứ tự tăng dần (cũ -> mới).
        """
        messages = await ChatMessageDocument.find(
            ChatMessageDocument.session_id == session_id,
            ChatMessageDocument.user_id == user_id,
            ChatMessageDocument.message_type == message_type,
        ).sort("-sequence").limit(limit).to_list()
        
        serialized = [self._serialize_doc(m) for m in messages]
        return list(reversed(serialized))

    async def list_sessions_by_user(
        self,
        user_id: str,
        limit: int,
        skip: int,
        status: Optional[str] = None,
    ) -> tuple[list[dict[str, Any]], int]:
        q_args = [ChatSessionDocument.user_id == user_id]
        if status:
            q_args.append(ChatSessionDocument.status == status)

        total = await ChatSessionDocument.find(*q_args).count()
        sessions = await ChatSessionDocument.find(*q_args).sort("-last_message_at").skip(skip).limit(limit).to_list()
        return [self._serialize_doc(s) for s in sessions], total

    async def list_messages_by_session(
        self,
        session_id: str,
        user_id: str,
        limit: int,
        skip: int,
    ) -> tuple[list[dict[str, Any]], int]:
        total = await ChatMessageDocument.find(
            ChatMessageDocument.session_id == session_id,
            ChatMessageDocument.user_id == user_id
        ).count()
        messages = await ChatMessageDocument.find(
            ChatMessageDocument.session_id == session_id,
            ChatMessageDocument.user_id == user_id
        ).sort("sequence").skip(skip).limit(limit).to_list()
        return [self._serialize_doc(m) for m in messages], total

    async def rename_session(self, session_id: str, user_id: str, title: str) -> bool:
        session = await ChatSessionDocument.find_one(
            ChatSessionDocument.session_id == session_id,
            ChatSessionDocument.user_id == user_id
        )
        if session:
            session.title = title
            await session.save()
            return True
        return False

    async def archive_session(self, session_id: str, user_id: str) -> bool:
        session = await ChatSessionDocument.find_one(
            ChatSessionDocument.session_id == session_id,
            ChatSessionDocument.user_id == user_id
        )
        if session:
            session.status = self.SESSION_STATUS_ARCHIVED
            await session.save()
            return True
        return False

    async def unarchive_session(self, session_id: str, user_id: str) -> bool:
        session = await ChatSessionDocument.find_one(
            ChatSessionDocument.session_id == session_id,
            ChatSessionDocument.user_id == user_id
        )
        if session:
            session.status = self.SESSION_STATUS_ACTIVE
            await session.save()
            return True
        return False

    async def delete_session(self, session_id: str, user_id: str) -> bool:
        session = await ChatSessionDocument.find_one(
            ChatSessionDocument.session_id == session_id,
            ChatSessionDocument.user_id == user_id
        )
        if session:
            await session.delete()
            await ChatMessageDocument.find(
                ChatMessageDocument.session_id == session_id,
                ChatMessageDocument.user_id == user_id
            ).delete()
            return True
        return False


_chat_history_repo: Optional[ChatHistoryRepository] = None


def get_chat_history_repository() -> ChatHistoryRepository:
    global _chat_history_repo
    if _chat_history_repo is None:
        _chat_history_repo = ChatHistoryRepository()
    return _chat_history_repo
