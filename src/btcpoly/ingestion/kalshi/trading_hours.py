"""Kalshi order-acceptance rules for BTC 15m up/down."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from btcpoly.timeutil import to_utc, utcnow


def _parse_ts(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return to_utc(value)
    text = str(value).strip()
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


def evaluate_trading_gate(
    raw: dict[str, Any],
    *,
    now: datetime | None = None,
    order_min_size: float = 1.0,
) -> TradingGate:
    """Whether Kalshi would accept a new order on this market now."""
    now_utc = to_utc(now or utcnow())
    status = str(raw.get("status") or "").lower()
    open_ts = _parse_ts(raw.get("open_time"))
    close_ts = _parse_ts(raw.get("close_time"))
    accepting = status in {"active", "open"}
    closed = status in {"closed", "finalized", "determined", "settled"}
    book_on = accepting and not closed

    seconds_left = None
    if close_ts is not None:
        seconds_left = max(0, int((close_ts - now_utc).total_seconds()))

    reason = "ok"
    ok = True
    if closed or status in {"finalized", "settled", "determined"}:
        ok, reason = False, "market_closed"
    elif status in {"initialized", "unopened"}:
        ok, reason = False, "market_not_started"
    elif not accepting:
        ok, reason = False, "not_accepting_orders"
    elif open_ts is not None and now_utc < open_ts:
        ok, reason = False, "market_not_started"
    elif close_ts is not None and now_utc >= close_ts:
        ok, reason = False, "window_ended"

    return TradingGate(
        ok=ok,
        reason=reason,
        accepting_orders=accepting and ok,
        closed=closed,
        enable_order_book=book_on and ok,
        order_min_size=float(order_min_size),
        event_start=open_ts,
        event_end=close_ts,
        is_current_window=ok,
        seconds_left=seconds_left,
    )
