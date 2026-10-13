"""Settle closed paper trades against Kalshi YES/NO resolution (UP/DOWN)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from btcpoly.config import Settings
from btcpoly.db.models import PaperTrade, PolymarketMarket
from btcpoly.db.session import session_scope
from btcpoly.ingestion.kalshi.markets import fetch_market_by_ticker, parse_winner
from btcpoly.paper.bankroll import get_bankroll
from btcpoly.timeutil import to_utc, utcnow

__all__ = [
    "compute_binary_pnl",
    "paper_pnl_stats",
    "parse_winner",
    "settle_paper_trades",
]


def compute_binary_pnl(*, size: float, entry_price: float, won: bool) -> tuple[float, float]:
    """Return (exit_price, pnl) for a binary share bought at entry_price."""
    if won:
        return 1.0, float(size) * (1.0 - float(entry_price))
    return 0.0, -float(size) * float(entry_price)


def paper_pnl_stats(session: Session) -> dict[str, Any]:
    open_q: Select[Any] = select(func.count()).select_from(PaperTrade).where(
        PaperTrade.decision.in_(("BUY_UP", "BUY_DOWN")),
        PaperTrade.pnl.is_(None),
    )
    settled_q: Select[Any] = select(func.count()).select_from(PaperTrade).where(
        PaperTrade.decision.in_(("BUY_UP", "BUY_DOWN")),
        PaperTrade.pnl.is_not(None),
    )
    wins_q: Select[Any] = select(func.count()).select_from(PaperTrade).where(
        PaperTrade.decision.in_(("BUY_UP", "BUY_DOWN")),
        PaperTrade.pnl > 0,
    )
    losses_q: Select[Any] = select(func.count()).select_from(PaperTrade).where(
        PaperTrade.decision.in_(("BUY_UP", "BUY_DOWN")),
        PaperTrade.pnl < 0,
    )
    pnl_q: Select[Any] = select(func.coalesce(func.sum(PaperTrade.pnl), 0.0)).where(
        PaperTrade.pnl.is_not(None),
    )
    open_n = int(session.scalar(open_q) or 0)
    settled_n = int(session.scalar(settled_q) or 0)
    wins = int(session.scalar(wins_q) or 0)
    losses = int(session.scalar(losses_q) or 0)
    pnl_total = float(session.scalar(pnl_q) or 0.0)
    decided = wins + losses
    win_rate = (wins / decided) if decided else None
    return {
        "open": open_n,
        "settled": settled_n,
        "wins": wins,
        "losses": losses,
        "pnl_total": pnl_total,
        "win_rate": win_rate,
    }


def _market_row(session: Session, market_id: str) -> PolymarketMarket | None:
    return session.scalar(select(PolymarketMarket).where(PolymarketMarket.market_id == market_id))


def _window_end(
    *,
    market: PolymarketMarket | None,
    raw: dict[str, Any] | None,
) -> datetime | None:
    if market is not None and market.end_ts is not None:
        return to_utc(market.end_ts)
    if raw and raw.get("close_time"):
        text = str(raw["close_time"]).replace("Z", "+00:00")
        try:
            return to_utc(datetime.fromisoformat(text))
        except ValueError:
            return None
    return None


def settle_paper_trades(settings: Settings) -> dict[str, Any]:
    now = utcnow()
    settled_rows: list[dict[str, Any]] = []
    skipped_open = 0
    skipped_unresolved = 0
    skipped_no_market = 0
    wins = 0
    losses = 0
    pnl_total = 0.0

    with session_scope() as session:
        trades = list(
            session.scalars(
                select(PaperTrade)
                .where(
                    PaperTrade.decision.in_(("BUY_UP", "BUY_DOWN")),
                    PaperTrade.pnl.is_(None),
                )
                .order_by(PaperTrade.id)
            ).all()
        )

        raw_cache: dict[str, dict[str, Any] | None] = {}
        winner_cache: dict[str, str | None] = {}

        for trade in trades:
            market = _market_row(session, trade.market_id)
            ticker = (market.slug if market else None) or trade.market_id
            if not ticker:
                skipped_no_market += 1
                continue

            if ticker not in raw_cache:
                try:
                    raw_cache[ticker] = fetch_market_by_ticker(settings, ticker)
                except Exception:  # noqa: BLE001
                    raw_cache[ticker] = None
                winner_cache[ticker] = (
                    parse_winner(raw_cache[ticker]) if raw_cache[ticker] else None
                )

            raw = raw_cache.get(ticker)
            end_ts = _window_end(market=market, raw=raw)
            if end_ts is not None and to_utc(end_ts) > now and winner_cache.get(ticker) is None:
                skipped_open += 1
                continue

            winner = winner_cache.get(ticker)
            if winner is None:
                skipped_unresolved += 1
                continue

            side = (trade.side or "").upper()
            if side not in {"UP", "DOWN"}:
                side = "UP" if trade.decision == "BUY_UP" else "DOWN"
            won = side == winner
            exit_price, binary_pnl = compute_binary_pnl(
                size=float(trade.size),
                entry_price=float(trade.entry_price),
                won=won,
            )
            fees = float(trade.fees or 0.0)
            slippage = float(trade.slippage or 0.0)
            pnl = binary_pnl - fees - slippage
            trade.exit_price = exit_price
            trade.pnl = pnl
            if market is not None:
                market.status = "resolved"
                extra = dict(market.raw_json or {})
                extra["paper_winner"] = winner
                extra["paper_settled_at"] = now.isoformat()
                if raw:
                    extra["resolved_raw"] = raw
                market.raw_json = extra

            settled_rows.append(
                {
                    "trade_id": trade.id,
                    "market_id": trade.market_id,
                    "slug": ticker,
                    "side": side,
                    "winner": winner,
                    "won": won,
                    "entry_price": trade.entry_price,
                    "exit_price": exit_price,
                    "size": trade.size,
                    "binary_pnl": binary_pnl,
                    "fees": fees,
                    "slippage": slippage,
                    "pnl": pnl,
                }
            )
            pnl_total += pnl
            if won:
                wins += 1
            else:
                losses += 1

        stats = paper_pnl_stats(session)
        bankroll = get_bankroll(session, settings)

    return {
        "settled": len(settled_rows),
        "skipped_open": skipped_open,
        "skipped_unresolved": skipped_unresolved,
        "skipped_no_market": skipped_no_market,
        "wins": wins,
        "losses": losses,
        "pnl_total": pnl_total,
        "trades": settled_rows,
        "paper_stats": stats,
        "bankroll": bankroll,
        "event_ts": now.isoformat(),
        "exchange": "kalshi",
    }
