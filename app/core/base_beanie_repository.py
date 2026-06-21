from __future__ import annotations

from abc import ABC
from typing import ClassVar, Generic, Optional, Type, TypeVar

from beanie import Document
from bson import ObjectId


DocT = TypeVar("DocT", bound=Document)


class BeanieRepository(ABC, Generic[DocT]):
    """Minimal Beanie persistence primitives for concrete repositories."""

    document_class: ClassVar[Type[DocT]]

    async def create(self, doc: DocT) -> DocT:
        await doc.insert()
        return doc

    async def find_by_id(self, doc_id: str) -> Optional[DocT]:
        if not ObjectId.is_valid(str(doc_id)):
            return None
        return await self.document_class.get(doc_id)

    async def save(self, doc: DocT) -> DocT:
        await doc.save()
        return doc

    async def delete(self, doc: DocT) -> None:
        await doc.delete()
