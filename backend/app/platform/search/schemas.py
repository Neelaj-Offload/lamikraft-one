"""Search API models."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.platform.search.models import QUERY_MAX_CHARS


class SearchHitRead(BaseModel):
    resource_type: str
    resource_id: uuid.UUID
    title: str
    subtitle: str | None
    path: str


class SearchGroupRead(BaseModel):
    resource_type: str
    group: str
    hits: list[SearchHitRead]
    #: more hits exist than the per-group limit returned ("See all results")
    has_more: bool


class SearchResults(BaseModel):
    query: str
    #: the literal terms every hit matched (no wildcards or patterns are ever derived from input)
    terms: list[str]
    groups: list[SearchGroupRead]
    #: groups whose provider failed this time (shown as unavailable, never as "no results")
    unavailable_groups: list[str] = Field(default_factory=list)


class RecentSearchRead(BaseModel):
    id: uuid.UUID
    query: str
    searched_at: datetime


class RecentSearchCreate(BaseModel):
    query: str = Field(min_length=1, max_length=QUERY_MAX_CHARS)
