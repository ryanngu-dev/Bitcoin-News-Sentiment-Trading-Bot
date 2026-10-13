"""UTC timestamp helpers. Naive datetimes are treated as UTC."""

from __future__ import annotations

import calendar
import re
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any


UTC = timezone.utc
_YMD = re.compile(r"^\d{8}$")


def utcnow() -> datetime:
    return datetime.now(tz=UTC)


def to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def parse_ts(value: Any) -> datetime:
    """Normalize unix seconds/ms, ISO-8601, RFC-2822, YYYYMMDD, struct_time, datetime to UTC."""
    if isinstance(value, datetime):
        return to_utc(value)
    if isinstance(value, time.struct_time):
        return datetime.fromtimestamp(calendar.timegm(value), tz=UTC)
    if isinstance(value, (tuple, list)) and len(value) >= 6:
        try:
            return datetime.fromtimestamp(calendar.timegm(tuple(value)[:9]), tz=UTC)
        except (TypeError, ValueError, OverflowError):
            pass
    if isinstance(value, (int, float)):
        ts = float(value)
        if ts > 1e12:
            ts = ts / 1000.0
        return datetime.fromtimestamp(ts, tz=UTC)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise ValueError("empty timestamp")
        if _YMD.fullmatch(text):
            return datetime.strptime(text, "%Y%m%d").replace(tzinfo=UTC)
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            return to_utc(datetime.fromisoformat(text))
        except ValueError:
            # RSS feeds use RFC-2822: "Tue, 25 Aug 2026 22:35:52 +0000"
            try:
                return to_utc(parsedate_to_datetime(text))
            except (TypeError, ValueError, IndexError) as exc:
                raise ValueError(f"unparseable timestamp: {value!r}") from exc
    raise TypeError(f"unsupported timestamp type: {type(value)!r}")


def available_at(event_ts: datetime, ingested_at: datetime, as_of: datetime) -> bool:
    """Point-in-time rule: both event and ingest must be <= as_of."""
    return to_utc(event_ts) <= to_utc(as_of) and to_utc(ingested_at) <= to_utc(as_of)
