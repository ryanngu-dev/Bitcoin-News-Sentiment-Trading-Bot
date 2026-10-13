"""Derived paper bankroll from starting cash + settled PnL - open cost."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from btcpoly.config import Settings
from btcpoly.db.models import PaperTrade


def get_bankroll(session: Session, settings: Settings) -> dict[str, Any]:
    starting = float(settings.paper.starting_cash)
    settled_pnl = float(
        session.scalar(
            select(func.coalesce(func.sum(PaperTrade.pnl), 0.0)).where(PaperTrade.pnl.is_not(None))
        )
        or 0.0
    )
    open_rows = list(
        session.scalars(
            select(PaperTrade).where(
                PaperTrade.decision.in_(("BUY_UP", "BUY_DOWN")),
                PaperTrade.pnl.is_(None),
            )
        ).all()
    )
    open_cost = 0.0
    for row in open_rows:
        open_cost += float(row.size) * float(row.entry_price)
        open_cost += float(row.fees or 0.0) + float(row.slippage or 0.0)
    cash = starting + settled_pnl - open_cost
    return {
        "starting_cash": starting,
        "settled_pnl": settled_pnl,
        "open_cost": open_cost,
        "open_positions": len(open_rows),
        "cash": cash,
        "exposure": open_cost,
        "max_position_usd": float(settings.risk.max_position_usd),
        "max_bankroll_pct": float(settings.risk.max_bankroll_pct),
    }


def max_trade_notional(bankroll: dict[str, Any], settings: Settings) -> float:
    cash = max(0.0, float(bankroll.get("cash") or 0.0))
    by_pct = cash * float(settings.risk.max_bankroll_pct)
    return max(0.0, min(float(settings.risk.max_position_usd), by_pct, cash))
