"""Reset paper ledger for a clean starting bankroll."""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete, func, select

from btcpoly.config import Settings
from btcpoly.db.models import PaperTrade, Prediction
from btcpoly.db.session import session_scope
from btcpoly.paper.bankroll import get_bankroll


def reset_paper_book(settings: Settings, *, clear_predictions: bool = True) -> dict[str, Any]:
    """Wipe paper trades (and predictions) so cash == starting_cash."""
    with session_scope() as session:
        before_trades = int(session.scalar(select(func.count()).select_from(PaperTrade)) or 0)
        before_preds = int(session.scalar(select(func.count()).select_from(Prediction)) or 0)
        session.execute(delete(PaperTrade))
        cleared_preds = 0
        if clear_predictions:
            session.execute(delete(Prediction))
            cleared_preds = before_preds
        session.flush()
        bankroll = get_bankroll(session, settings)
    return {
        "cleared_paper_trades": before_trades,
        "cleared_predictions": cleared_preds,
        "bankroll": bankroll,
        "starting_cash": float(settings.paper.starting_cash),
    }
