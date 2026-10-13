"""5m / 15m Polymarket Up/Down market mode helpers."""

from __future__ import annotations

import re
from dataclasses import replace

from btcpoly.config import Settings

# Polymarket event slugs: btc-updown-5m-{unix} / btc-updown-15m-{unix}
SUPPORTED_DURATIONS: tuple[int, ...] = (5, 15)
_SLUG_DURATION_RE = re.compile(r"btc-updown-(\d+)m(?:-|$)", re.IGNORECASE)


def slug_prefix_for_duration(minutes: int) -> str:
    minutes = int(minutes)
    if minutes not in SUPPORTED_DURATIONS:
        raise ValueError(f"duration must be one of {SUPPORTED_DURATIONS}, got {minutes}")
    return f"btc-updown-{minutes}m"


def with_market_duration(settings: Settings, minutes: int) -> Settings:
    """Return settings pointed at the 5m or 15m BTC Up/Down market."""
    minutes = int(minutes)
    prefix = slug_prefix_for_duration(minutes)
    return replace(
        settings,
        polymarket=replace(
            settings.polymarket,
            market_duration_minutes=minutes,
            slug_prefix=prefix,
        ),
    )


def duration_minutes_from_slug(slug: str | None) -> int | None:
    if not slug:
        return None
    match = _SLUG_DURATION_RE.search(str(slug))
    if not match:
        return None
    minutes = int(match.group(1))
    return minutes if minutes > 0 else None


def resolve_window_duration_minutes(slug: str | None, fallback: int) -> int:
    """Prefer duration encoded in the slug so 5m/15m trades settle correctly after mode switches."""
    parsed = duration_minutes_from_slug(slug)
    return int(parsed) if parsed is not None else int(fallback)
