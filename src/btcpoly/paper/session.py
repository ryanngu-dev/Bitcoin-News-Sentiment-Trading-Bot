"""Paper session gates for ``btcpoly run`` (reset bankroll, window skip, news sentiment)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from rich.console import Console

from btcpoly.config import Settings
from btcpoly.ingestion.kalshi.markets import resolve_active_market
from btcpoly.paper.reset import reset_paper_book
from btcpoly.timeutil import utcnow


@dataclass(frozen=True)
class PaperSessionState:
    """Active only for ``btcpoly run``; not used by one-shot ``execute``."""

    started_at: datetime
    skip_market_slug: str | None
    reset_cleared_trades: int = 0


def begin_paper_session(
    settings: Settings,
    *,
    console: Console | None = None,
    reset: bool | None = None,
    wait_next_window: bool | None = None,
) -> PaperSessionState:
    """Reset ledger (optional) and block trades in the Kalshi window active at start."""
    do_reset = settings.paper.reset_on_run if reset is None else reset
    do_wait = settings.paper.wait_next_window_on_run if wait_next_window is None else wait_next_window

    cleared = 0
    if do_reset:
        payload = reset_paper_book(settings)
        cleared = int(payload.get("cleared_paper_trades") or 0)
        if console is not None:
            cash = float((payload.get("bankroll") or {}).get("cash") or settings.paper.starting_cash)
            console.print(
                f"[green]Session bankroll reset[/green] — cleared {cleared} paper trade(s), "
                f"cash [bold]${cash:,.2f}[/bold]"
            )

    skip_slug: str | None = None
    if do_wait:
        try:
            market = resolve_active_market(settings)
            skip_slug = str(market.slug or market.market_id or "") or None
        except Exception:  # noqa: BLE001
            skip_slug = None
        if console is not None:
            if skip_slug:
                console.print(
                    f"[yellow]Waiting for next 15m window[/yellow] — no trades on "
                    f"[dim]{skip_slug}[/dim] (started mid-window)"
                )
            else:
                console.print(
                    "[yellow]Could not resolve live Kalshi window[/yellow] — "
                    "window skip disabled until market resolves"
                )

    if console is not None and settings.paper.require_fresh_btc_sentiment:
        console.print(
            f"[dim]Trades need fresh BTC news: ≥{settings.paper.min_mention_count_900} mention(s) in "
            f"15m and sentiment aligned with side (min |sentiment| "
            f"{settings.paper.min_sentiment_net_900:.2f}).[/dim]"
        )

    return PaperSessionState(
        started_at=utcnow(),
        skip_market_slug=skip_slug,
        reset_cleared_trades=cleared,
    )


def _effective_sentiment(features: dict[str, Any]) -> tuple[float, int, int]:
    lex = float(features.get("sentiment_net_900") or 0.0)
    ai_n = int(features.get("ai_sentiment_scored_900") or 0)
    ai = float(features.get("ai_sentiment_net_900") or 0.0)
    mentions = int(features.get("mention_count_900") or 0)
    if ai_n > 0:
        blended = (lex + ai) / 2.0
    else:
        blended = lex
    return blended, mentions, ai_n


def session_trade_block(
    settings: Settings,
    *,
    session: PaperSessionState | None,
    decision: str,
    slug: str,
    features: dict[str, Any],
) -> str | None:
    """Return a NO_TRADE reason if session rules veto this buy, else None."""
    if decision not in {"BUY_UP", "BUY_DOWN"}:
        return None

    if session is not None and session.skip_market_slug:
        if slug == session.skip_market_slug:
            return "session_wait_next_window"

    if not settings.paper.require_fresh_btc_sentiment:
        return None

    sentiment, mentions, _ai_n = _effective_sentiment(features)
    min_mentions = int(settings.paper.min_mention_count_900)
    min_sent = float(settings.paper.min_sentiment_net_900)

    if mentions < min_mentions:
        return "no_recent_btc_news"

    if decision == "BUY_UP":
        if sentiment < min_sent:
            return "btc_sentiment_not_bullish"
    elif decision == "BUY_DOWN":
        if sentiment > -min_sent:
            return "btc_sentiment_not_bearish"

    return None


__all__ = [
    "PaperSessionState",
    "begin_paper_session",
    "session_trade_block",
]
