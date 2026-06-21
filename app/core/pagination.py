from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, List, TypeVar


T = TypeVar("T")


@dataclass
class PagedResult(Generic[T]):
    items: List[T]
    total: int
    page: int
    limit: int

    @property
    def skip(self) -> int:
        return (self.page - 1) * self.limit

    @property
    def total_pages(self) -> int:
        return (self.total + self.limit - 1) // self.limit if self.limit > 0 else 1

    @property
    def has_next(self) -> bool:
        return self.page < self.total_pages

    @property
    def has_prev(self) -> bool:
        return self.page > 1
