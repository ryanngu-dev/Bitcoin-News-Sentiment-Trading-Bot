"""Polymarket order-acceptance rules for BTC Up/Down windows.

Paper (and later live) entries must mirror Gamma/CLOB gates:
- acceptingOrders / not closed / order book enabled
- only the *current* live window (eventStart → eventEnd)
- size >= orderMinSize (usually 5 shares)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from btcpoly.ingestion.polymarket.slug import market_slug, window_seconds
from btcpoly.timeutil import to_utc, utcnow


def _parse_ts(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return to_utc(value)
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return to_utc(datetime.fromisoformat(text))
    except ValueError:
        return None


@dataclass(frozen=True)
class TradingGate:
    ok: bool
    reason: str
    accepting_orders: bool
    closed: bool
    enable_order_book: bool
    order_min_size: float
    event_start: datetime | None
    event_end: datetime | None
    is_current_window: bool
    seconds_left: int | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "reason": self.reason,
            "accepting_orders": self.accepting_orders,
            "closed": self.closed,
            "enable_order_book": self.enable_order_book,
            "order_min_size": self.order_min_size,
            "event_start": self.event_start.isoformat() if self.event_start else None,
            "event_end": self.event_end.isoformat() if self.event_end else None,
            "is_current_window": self.is_current_window,
            "seconds_left": self.seconds_left,
        }


def event_bounds(
    raw: dict[str, Any],
    *,
    slug: str,
    duration_minutes: int,
) -> tuple[datetime | None, datetime | None]:
    """Prefer Gamma eventStartTime; fall back to slug window timestamps."""
    start = _parse_ts(raw.get("eventStartTime"))
    if start is None:
        try:
            start_unix = int(str(slug).rsplit("-", 1)[-1])
            start = datetime.fromtimestamp(start_unix, tz=timezone.utc)
        except ValueError:
            start = None
    if start is None:
        return None, None
    end = start.timestamp() + window_seconds(duration_minutes)
    return start, datetime.fromtimestamp(end, tz=timezone.utc)


def evaluate_trading_gate(
    raw: dict[str, Any],
    *,
    slug: str,
    duration_minutes: int,
    slug_prefix: str,
    now: datetime | None = None,
) -> TradingGate:
    """Return whether Polymarket would accept a new order on this market now."""
    now_utc = to_utc(now or utcnow())
    accepting = bool(raw.get("acceptingOrders", False))
    closed = bool(raw.get("closed", False))
    book_on = bool(raw.get("enableOrderBook", True))
    min_size = float(raw.get("orderMinSize") or 5.0)
    event_start, event_end = event_bounds(raw, slug=slug, duration_minutes=duration_minutes)

    current_slug = market_slug(slug_prefix, duration_minutes=duration_minutes, now=now_utc)
    is_current = str(raw.get("slug") or slug) == current_slug or slug == current_slug

    seconds_left = None
    if event_end is not None:
        seconds_left = max(0, int((event_end - now_utc).total_seconds()))

    reason = "ok"
    ok = True
    if closed:
        ok, reason = False, "market_closed"
    elif not accepting:
        ok, reason = False, "not_accepting_orders"
    elif not book_on:
        ok, reason = False, "order_book_disabled"
    elif event_start is not None and now_utc < event_start:
        ok, reason = False, "market_not_started"
    elif event_end is not None and now_utc >= event_end:
        ok, reason = False, "window_ended"
    elif not is_current:
        ok, reason = False, "not_current_window"

    return TradingGate(
        ok=ok,
        reason=reason,
        accepting_orders=accepting,
        closed=closed,
        enable_order_book=book_on,
        order_min_size=min_size,
        event_start=event_start,
        event_end=event_end,
        is_current_window=is_current,
        seconds_left=seconds_left,
    )
