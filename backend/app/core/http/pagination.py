"""The list envelope. Filters are always applied before LIMIT/OFFSET."""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")

MAX_LIMIT = 200


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


class PageParams(BaseModel):
    limit: int = Field(default=50, ge=1, le=MAX_LIMIT)
    offset: int = Field(default=0, ge=0)
