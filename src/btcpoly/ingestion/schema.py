from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator

from btcpoly.timeutil import parse_ts, utcnow


class RawPost(BaseModel):
    """Canonical attention item. Preserve original event_ts and ingest time."""

    model_config = ConfigDict(extra="allow")

    platform: str
    post_id: str
    author: str | None = None
    event_ts: datetime
    ingested_at: datetime = Field(default_factory=utcnow)
    text: str | None = None
    views: int | None = None
    likes: int | None = None
    replies: int | None = None
    reposts: int | None = None
    engagement: float | None = None
    author_followers: int | None = None
    url: str | None = None
    raw_json: dict[str, Any] = Field(default_factory=dict)

    @field_validator("event_ts", "ingested_at", mode="before")
    @classmethod
    def _normalize_ts(cls, value: Any) -> datetime:
        return parse_ts(value)


class Collector(Protocol):
    name: str

    def collect(self) -> list[RawPost]:
        ...
