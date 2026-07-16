from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from pymongo import ReturnDocument

from app.core.exceptions import NotFoundException
from app.modules.chat.dtos.faq_recommendation import FaqRecommendation
from app.modules.chat.dtos.send_message import TokenUsage
from app.modules.chat.models.chat_session import ChatSessionDocument
from app.modules.chat.models.chat_message import ChatMessageDocument
from app.modules.rag.query.dtos import SourceCitation

# Single source of truth for which pipeline step types are persisted to MongoDB.
PERSISTED_STEP_TYPES = frozenset({
    "query_analysis",
    "corpus_tree",
    "corpus_traversal",
    "faq_retrieval",
    "faq_answer",
    "file_retrieval",
    "document_read",
})


class ChatHistoryRepository:
    """MongoDB repository for chat sessions and messages using Beanie ODM."""

    SESSION_STATUS_ACTIVE = "active"
    SESSION_STATUS_ARCHIVED = "archived"

    async def ensure_session(self, session_id: str, user_id: str) -> ChatSessionDocument:
        now = datetime.now(timezone.utc)
        coll = ChatSessionDocument.get_motor_collection()
        await coll.find_one_and_update(
            {"session_id": session_id, "user_id": user_id},
            {
                "$setOnInsert": {
                    "session_id": session_id,
                    "user_id": user_id,
                    "title": None,
                    "metadata": {},
                    "message_count": 0,
                    "created_at": now,
                },
                "$set": {
                    "updated_at": now,
                    "last_message_at": now,
                    "status": self.SESSION_STATUS_ACTIVE,
                }
            },
            upsert=True,
        )
        session = await ChatSessionDocument.find_one(
            ChatSessionDocument.session_id == session_id,
            ChatSessionDocument.user_id == user_id
        )
        return session

    async def append_message(
        self,
        session_id: str,
        user_id: str,
        role: str,
        content: str,
        token_usage: Optional[TokenUsage | dict[str, Any]] = None,
        sources: Optional[list[SourceCitation | dict[str, Any]]] = None,
        steps: Optional[list[dict[str, Any]]] = None,
        processing_time_ms: Optional[int] = None,
        message_type: str = "text",
        faq_recommendation: Optional[FaqRecommendation | dict[str, Any]] = None,
    ) -> ChatMessageDocument:
        now = datetime.now(timezone.utc)
        coll = ChatSessionDocument.get_motor_collection()
        
        session_doc = await coll.find_one_and_update(
            {"session_id": session_id, "user_id": user_id},
            {
                "$inc": {"message_count": 1},
                "$set": {
                    "last_message_at": now,
                    "updated_at": now,
                    "status": self.SESSION_STATUS_ACTIVE
                },
                "$setOnInsert": {
                    "session_id": session_id,
                    "user_id": user_id,
                    "title": None,
                    "metadata": {},
                    "created_at": now,
                }
            },
            upsert=True,
            return_document=ReturnDocument.AFTER
        )
        
        sequence = session_doc["message_count"]
        
        if role == "user" and sequence == 1:
            await coll.update_one(
                {"session_id": session_id, "user_id": user_id, "title": None},
                {"$set": {"title": content}}
            )

        # Enforce the persistence whitelist
        persisted_steps = [
            s
            for s in (steps or [])
            if isinstance(s, dict) and s.get("type") in PERSISTED_STEP_TYPES
        ]
        token_usage_model = TokenUsage.model_validate(token_usage) if token_usage else None
        source_models = [SourceCitation.model_validate(source) for source in (sources or [])]
        faq_recommendation_model = (
            FaqRecommendation.model_validate(faq_recommendation)
            if faq_recommendation
            else None
        )

        message_doc = ChatMessageDocument(
            session_id=session_id,
            user_id=user_id,
            role=role,
            content=content,
            message_type=message_type,
            token_usage=token_usage_model,
            sources=source_models,
            steps=persisted_steps,
            processing_time_ms=processing_time_ms,
            faq_recommendation=faq_recommendation_model,
            sequence=sequence,
        )
        await message_doc.insert()
        return message_doc

    async def get_recent_messages(
        self,
        session_id: str,
        user_id: str,
        limit: int = 6,
        message_type: str = "text",
    ) -> list[ChatMessageDocument]:
        """
        Lấy (limit) tin nhắn cuối cùng của session, chỉ lấy message_type='text'.
        Trả về danh sách dict theo thứ tự tăng dần (cũ -> mới).
        """
        messages = await ChatMessageDocument.find(
            ChatMessageDocument.session_id == session_id,
            ChatMessageDocument.user_id == user_id,
            ChatMessageDocument.message_type == message_type,
        ).sort("-sequence").limit(limit).to_list()
        
        return list(reversed(messages))

    async def list_sessions_by_user(
        self,
        user_id: str,
        limit: int,
        skip: int,
        status: Optional[str] = None,
    ) -> tuple[list[ChatSessionDocument], int]:
        q_args = [ChatSessionDocument.user_id == user_id]
        if status:
            q_args.append(ChatSessionDocument.status == status)

        total = await ChatSessionDocument.find(*q_args).count()
        sessions = await ChatSessionDocument.find(*q_args).sort("-last_message_at").skip(skip).limit(limit).to_list()
        return sessions, total

    async def list_messages_by_session(
        self,
        session_id: str,
        user_id: str,
        limit: int,
        skip: int,
    ) -> tuple[list[ChatMessageDocument], int]:
        # Verify session existence
        session = await ChatSessionDocument.find_one(
            ChatSessionDocument.session_id == session_id,
            ChatSessionDocument.user_id == user_id
        )
        if not session:
            raise NotFoundException("Session", session_id)

        total = await ChatMessageDocument.find(
            ChatMessageDocument.session_id == session_id,
            ChatMessageDocument.user_id == user_id
        ).count()
        messages = await ChatMessageDocument.find(
            ChatMessageDocument.session_id == session_id,
            ChatMessageDocument.user_id == user_id
        ).sort("sequence").skip(skip).limit(limit).to_list()
        return messages, total

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
            # Delete messages first to prevent orphan messages if session delete fails
            await ChatMessageDocument.find(
                ChatMessageDocument.session_id == session_id,
                ChatMessageDocument.user_id == user_id
            ).delete()
            await session.delete()
            return True
        return False


_chat_history_repo: Optional[ChatHistoryRepository] = None


def get_chat_history_repository() -> ChatHistoryRepository:
    global _chat_history_repo
    if _chat_history_repo is None:
        _chat_history_repo = ChatHistoryRepository()
    return _chat_history_repo
