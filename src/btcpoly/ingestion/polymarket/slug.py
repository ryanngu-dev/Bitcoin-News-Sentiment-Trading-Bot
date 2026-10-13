"""Polymarket Up/Down slug helpers (5m / 15m windows)."""

from __future__ import annotations

from datetime import datetime, timezone

from btcpoly.ingestion.polymarket.mode import slug_prefix_for_duration


def window_seconds(duration_minutes: int) -> int:
    return max(60, int(duration_minutes) * 60)


def window_start_unix(now: datetime | None = None, *, duration_minutes: int = 15) -> int:
    ts = int((now or datetime.now(tz=timezone.utc)).timestamp())
    step = window_seconds(duration_minutes)
    return (ts // step) * step


def market_slug(
    slug_prefix: str,
    *,
    duration_minutes: int = 15,
    now: datetime | None = None,
    offset_windows: int = 0,
) -> str:
    try:
        default_prefix = slug_prefix_for_duration(duration_minutes)
    except ValueError:
        default_prefix = f"btc-updown-{int(duration_minutes)}m"
    prefix = (slug_prefix or default_prefix).rstrip("-")
    start = window_start_unix(now, duration_minutes=duration_minutes)
    start += offset_windows * window_seconds(duration_minutes)
    return f"{prefix}-{start}"


def candidate_slugs(
    slug_prefix: str,
    *,
    duration_minutes: int = 15,
    now: datetime | None = None,
) -> list[str]:
    """Current window, then neighbors (handles edge-of-window / lag)."""
    return [
        market_slug(slug_prefix, duration_minutes=duration_minutes, now=now, offset_windows=off)
        for off in (0, -1, 1)
    ]
