"""Polymarket CLOB order book helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

from btcpoly.config import Settings
from btcpoly.db.models import PolymarketBook
from btcpoly.db.session import session_scope
from btcpoly.ingestion.collectors.http import fetch_text
from btcpoly.ingestion.polymarket.gamma import ResolvedMarket
from btcpoly.timeutil import utcnow

_TIMEOUT = 12


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


def _levels(side: Any) -> list[dict[str, Any]]:
    if not isinstance(side, list):
        return []
    out: list[dict[str, Any]] = []
    for level in side:
        if isinstance(level, dict):
            price = level.get("price")
            size = level.get("size")
        elif isinstance(level, (list, tuple)) and len(level) >= 2:
            price, size = level[0], level[1]
        else:
            continue
        try:
            out.append({"price": float(price), "size": float(size)})
        except (TypeError, ValueError):
            continue
    return out


def _best(levels: list[dict[str, Any]], *, side: str) -> float | None:
    if not levels:
        return None
    prices = [float(x["price"]) for x in levels]
    return max(prices) if side == "bid" else min(prices)


def fetch_token_book(settings: Settings, token_id: str) -> TokenBook:
    base = settings.polymarket.clob_base.rstrip("/")
    query = urlencode({"token_id": token_id})
    url = f"{base}/book?{query}"
    payload = json.loads(fetch_text(url, timeout=_TIMEOUT, attempts=2))
    bids = _levels(payload.get("bids"))
    asks = _levels(payload.get("asks"))
    best_bid = _best(bids, side="bid")
    best_ask = _best(asks, side="ask")
    mid = None
    spread = None
    if best_bid is not None and best_ask is not None:
        mid = (best_bid + best_ask) / 2.0
        spread = best_ask - best_bid
    elif best_ask is not None:
        mid = best_ask
    elif best_bid is not None:
        mid = best_bid
    return TokenBook(
        token_id=token_id,
        best_bid=best_bid,
        best_ask=best_ask,
        mid=mid,
        spread=spread,
        bids=bids[:10],
        asks=asks[:10],
    )


def _persist_book(market_id: str, book: TokenBook) -> None:
    now = utcnow()
    with session_scope() as session:
        session.add(
            PolymarketBook(
                market_id=market_id,
                token_id=book.token_id,
                event_ts=now,
                ingested_at=now,
                best_bid=book.best_bid,
                best_ask=book.best_ask,
                spread=book.spread,
                bids=book.bids,
                asks=book.asks,
            )
        )


def fetch_market_odds(settings: Settings, market: ResolvedMarket) -> MarketOdds:
    up = fetch_token_book(settings, market.up_token_id)
    down = fetch_token_book(settings, market.down_token_id)
    _persist_book(market.market_id, up)
    _persist_book(market.market_id, down)

    source = "clob"
    p_up = up.mid
    p_down = down.mid
    if p_up is None or p_down is None:
        gamma_up, gamma_down = market.outcome_prices
        if p_up is None and gamma_up is not None:
            p_up = gamma_up
            source = "gamma"
        if p_down is None and gamma_down is not None:
            p_down = gamma_down
            source = "gamma" if source == "gamma" else "mixed"

    if p_up is None and p_down is not None:
        p_up = max(0.0, min(1.0, 1.0 - p_down))
    if p_down is None and p_up is not None:
        p_down = max(0.0, min(1.0, 1.0 - p_up))
    if p_up is None or p_down is None:
        raise RuntimeError(f"no prices for market {market.slug}")

    # Normalize lightly if both present and drift from 1.
    total = p_up + p_down
    if total > 0:
        p_up_n = p_up / total
        p_down_n = p_down / total
    else:
        p_up_n, p_down_n = 0.5, 0.5

    up_ask = up.best_ask if up.best_ask is not None else p_up_n
    down_ask = down.best_ask if down.best_ask is not None else p_down_n

    return MarketOdds(
        market_id=market.market_id,
        slug=market.slug,
        up=up,
        down=down,
        p_up_mid=float(p_up_n),
        p_down_mid=float(p_down_n),
        up_ask=float(up_ask),
        down_ask=float(down_ask),
        spread_up=up.spread,
        source=source,
    )
