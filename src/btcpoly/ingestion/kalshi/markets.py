"""Resolve live Kalshi BTC up/down markets and mid prices."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select

from btcpoly.config import Settings
from btcpoly.db.models import PolymarketBook, PolymarketMarket
from btcpoly.db.session import session_scope
from btcpoly.ingestion.kalshi.client import api_get, as_float
from btcpoly.ingestion.kalshi.trading_hours import evaluate_trading_gate
from btcpoly.timeutil import to_utc, utcnow


@dataclass(frozen=True)
class ResolvedMarket:
    market_id: str
    slug: str
    question: str | None
    up_token_id: str
    down_token_id: str
    start_ts: datetime | None
    end_ts: datetime | None
    outcome_prices: tuple[float | None, float | None]
    raw: dict[str, Any]
    accepting_orders: bool = True
    closed: bool = False
    order_min_size: float = 1.0
    tradable: bool = True
    tradable_reason: str = "ok"
    floor_strike: float | None = None


@dataclass(frozen=True)
class TokenBook:
    token_id: str
    best_bid: float | None
    best_ask: float | None
    mid: float | None
    spread: float | None
    bids: list[Any]
    asks: list[Any]


@dataclass(frozen=True)
class MarketOdds:
    market_id: str
    slug: str
    up: TokenBook
    down: TokenBook
    p_up_mid: float
    p_down_mid: float
    up_ask: float
    down_ask: float
    spread_up: float | None
    source: str


def _parse_ts(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    try:
        return to_utc(datetime.fromisoformat(text))
    except ValueError:
        return None


def fetch_markets(settings: Settings, *, status: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
    params: dict[str, Any] = {
        "series_ticker": settings.kalshi.series_ticker,
        "limit": int(limit),
    }
    if status:
        params["status"] = status
    payload = api_get(settings, "/markets", params)
    markets = payload.get("markets") or []
    return [m for m in markets if isinstance(m, dict)]


def fetch_market_by_ticker(settings: Settings, ticker: str) -> dict[str, Any] | None:
    try:
        payload = api_get(settings, f"/markets/{ticker}")
    except Exception:  # noqa: BLE001
        return None
    market = payload.get("market")
    return market if isinstance(market, dict) else None


def expand_ticker_candidates(value: str) -> list[str]:
    """Accept a Kalshi URL or short ticker and expand to API ticker candidates.

    Example:
      https://kalshi.com/.../kxbtc15m-26aug262030
      → KXBTC15M-26AUG262030, KXBTC15M-26AUG262030-30
    """
    text = (value or "").strip()
    if not text:
        return []
    if "://" in text or "/" in text:
        text = text.rstrip("/").split("/")[-1]
    base = text.strip().upper()
    out: list[str] = []
    for cand in (base,):
        if cand and cand not in out:
            out.append(cand)
    # Short form omits the trailing -MM minute suffix used by Kalshi.
    if base.count("-") == 1:
        _series, rest = base.split("-", 1)
        if len(rest) >= 2 and rest[-2:].isdigit():
            full = f"{base}-{rest[-2:]}"
            if full not in out:
                out.append(full)
    return out


def pick_live_market(markets: list[dict[str, Any]], *, now: datetime | None = None) -> dict[str, Any] | None:
    now_utc = to_utc(now or utcnow())
    live: list[dict[str, Any]] = []
    for raw in markets:
        status = str(raw.get("status") or "").lower()
        if status not in {"active", "open"}:
            continue
        start = _parse_ts(raw.get("open_time"))
        end = _parse_ts(raw.get("close_time"))
        if start is not None and now_utc < start:
            continue
        if end is not None and now_utc >= end:
            continue
        live.append(raw)
    if not live:
        return None
    live.sort(key=lambda m: _parse_ts(m.get("close_time")) or now_utc)
    return live[0]


def resolve_active_market(settings: Settings) -> ResolvedMarket:
    """Current live Kalshi BTC up/down contract (YES=up / NO=down vs strike)."""
    raw: dict[str, Any] | None = None

    # Prefer status=open: the unfiltered series list is dominated by future
    # `initialized` windows and can push the live contract past the page limit.
    for status in ("open", None):
        try:
            markets = fetch_markets(settings, status=status, limit=200)
        except Exception:  # noqa: BLE001
            markets = []
        raw = pick_live_market(markets)
        if raw is not None:
            break

    # Optional URL/ticker hint (e.g. from a Kalshi share link).
    hint = str(getattr(settings.kalshi, "market_ticker", "") or "").strip()
    if raw is None and hint:
        for cand in expand_ticker_candidates(hint):
            got = fetch_market_by_ticker(settings, cand)
            if got is None:
                continue
            raw = pick_live_market([got])
            if raw is not None:
                break

    if raw is None:
        raise RuntimeError(f"no active Kalshi market for series {settings.kalshi.series_ticker}")

    ticker = str(raw.get("ticker") or "")
    if not ticker:
        raise RuntimeError("kalshi market missing ticker")

    yes_ask = as_float(raw.get("yes_ask_dollars"), 0.5)
    no_ask = as_float(raw.get("no_ask_dollars"), 0.5)
    yes_bid = as_float(raw.get("yes_bid_dollars"), yes_ask)
    no_bid = as_float(raw.get("no_bid_dollars"), no_ask)
    p_up = (yes_bid + yes_ask) / 2.0 if yes_ask or yes_bid else yes_ask
    p_down = (no_bid + no_ask) / 2.0 if no_ask or no_bid else no_ask

    gate = evaluate_trading_gate(raw, order_min_size=settings.kalshi.order_min_size)
    start_ts = _parse_ts(raw.get("open_time"))
    end_ts = _parse_ts(raw.get("close_time"))
    strike = raw.get("floor_strike")
    title = str(raw.get("title") or raw.get("yes_sub_title") or ticker)
    resolved = ResolvedMarket(
        market_id=ticker,
        slug=ticker,
        question=title,
        up_token_id=f"{ticker}:YES",
        down_token_id=f"{ticker}:NO",
        start_ts=start_ts,
        end_ts=end_ts,
        outcome_prices=(p_up, p_down),
        raw=raw,
        accepting_orders=gate.accepting_orders,
        closed=gate.closed,
        order_min_size=gate.order_min_size,
        tradable=gate.ok,
        tradable_reason=gate.reason,
        floor_strike=float(strike) if strike not in (None, "") else None,
    )
    _upsert_market(resolved)
    return resolved


def fetch_market_odds(settings: Settings, market: ResolvedMarket) -> MarketOdds:
    raw = market.raw
    yes_ask = as_float(raw.get("yes_ask_dollars"), 0.5)
    no_ask = as_float(raw.get("no_ask_dollars"), 0.5)
    yes_bid = as_float(raw.get("yes_bid_dollars"), yes_ask)
    no_bid = as_float(raw.get("no_bid_dollars"), no_ask)
    # Prefer fresh quote if available.
    fresh = fetch_market_by_ticker(settings, market.slug) or raw
    yes_ask = as_float(fresh.get("yes_ask_dollars"), yes_ask)
    no_ask = as_float(fresh.get("no_ask_dollars"), no_ask)
    yes_bid = as_float(fresh.get("yes_bid_dollars"), yes_bid)
    no_bid = as_float(fresh.get("no_bid_dollars"), no_bid)

    up_mid = (yes_bid + yes_ask) / 2.0
    down_mid = (no_bid + no_ask) / 2.0
    spread = max(0.0, yes_ask - yes_bid)
    up = TokenBook("YES", yes_bid, yes_ask, up_mid, spread, [], [])
    down = TokenBook("NO", no_bid, no_ask, down_mid, max(0.0, no_ask - no_bid), [], [])

    now = utcnow()
    with session_scope() as session:
        session.add(
            PolymarketBook(
                market_id=market.market_id,
                token_id="YES",
                event_ts=now,
                ingested_at=now,
                best_bid=yes_bid,
                best_ask=yes_ask,
                spread=spread,
                bids=[],
                asks=[],
            )
        )

    return MarketOdds(
        market_id=market.market_id,
        slug=market.slug,
        up=up,
        down=down,
        p_up_mid=up_mid,
        p_down_mid=down_mid,
        up_ask=yes_ask,
        down_ask=no_ask,
        spread_up=spread,
        source="kalshi",
    )


def parse_winner(raw: dict[str, Any]) -> str | None:
    """Map Kalshi YES/NO result to UP/DOWN (YES = above strike = UP)."""
    result = str(raw.get("result") or "").strip().lower()
    if result in {"yes", "y"}:
        return "UP"
    if result in {"no", "n"}:
        return "DOWN"
    status = str(raw.get("status") or "").lower()
    if status in {"finalized", "settled", "determined"}:
        # Extreme quotes as last resort.
        yes_ask = as_float(raw.get("yes_ask_dollars"), 0.5)
        no_ask = as_float(raw.get("no_ask_dollars"), 0.5)
        if yes_ask >= 0.95 and yes_ask >= no_ask:
            return "UP"
        if no_ask >= 0.95 and no_ask >= yes_ask:
            return "DOWN"
    return None


def _upsert_market(resolved: ResolvedMarket) -> None:
    now = utcnow()
    with session_scope() as session:
        existing = session.scalar(
            select(PolymarketMarket).where(PolymarketMarket.market_id == resolved.market_id)
        )
        if existing is None:
            session.add(
                PolymarketMarket(
                    market_id=resolved.market_id,
                    slug=resolved.slug,
                    question=resolved.question,
                    up_token_id=resolved.up_token_id,
                    down_token_id=resolved.down_token_id,
                    start_ts=resolved.start_ts,
                    end_ts=resolved.end_ts,
                    ingested_at=now,
                    status="active" if resolved.tradable else resolved.tradable_reason,
                    raw_json=resolved.raw,
                )
            )
            return
        existing.slug = resolved.slug
        existing.question = resolved.question
        existing.up_token_id = resolved.up_token_id
        existing.down_token_id = resolved.down_token_id
        existing.start_ts = resolved.start_ts
        existing.end_ts = resolved.end_ts
        existing.ingested_at = now
        existing.status = "active" if resolved.tradable else resolved.tradable_reason
        existing.raw_json = resolved.raw
