"""Continuous paper run loop: market ticks, trades, and end-of-window summaries."""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any, Callable

from rich.console import Console
from rich.text import Text
from sqlalchemy import select
from sqlalchemy.orm import Session

from btcpoly.config import Settings
from btcpoly.db.models import PaperTrade, PolymarketMarket
from btcpoly.db.session import session_scope
from btcpoly.ingestion.kalshi.markets import fetch_market_odds, resolve_active_market
from btcpoly.ingestion.kalshi.trading_hours import evaluate_trading_gate
from btcpoly.paper.bankroll import get_bankroll
from btcpoly.paper.execute import execute_paper
from btcpoly.paper.rationale import build_trade_rationale
from btcpoly.paper.session import PaperSessionState, begin_paper_session
from btcpoly.paper.settle import paper_pnl_stats, settle_paper_trades
from btcpoly.timeutil import to_utc, utcnow


_BANNER_BAR = "=" * 64


def _ts(now: datetime | None = None) -> str:
    return (now or utcnow()).strftime("%H:%M:%S")


def format_banner(lines: list[str], *, style: str = "bold white") -> Text:
    """Loud multi-line announcement, separated from tick noise."""
    text = Text()
    text.append("\n\n")
    text.append(f"{_BANNER_BAR}\n", style=style)
    text.append(f"{_BANNER_BAR}\n", style=style)
    for line in lines:
        text.append(f"  {line}\n", style=style)
    text.append(f"{_BANNER_BAR}\n", style=style)
    text.append(f"{_BANNER_BAR}\n", style=style)
    text.append("\n")
    return text


def _bet_usd(payload: dict[str, Any]) -> float:
    size = float(payload.get("size") or 0.0)
    entry = float(payload.get("entry_price") or 0.0)
    fees = float(payload.get("fees") or 0.0)
    slip = float(payload.get("slippage") or 0.0)
    return size * entry + fees + slip


def _session_banner_line(
    *,
    elapsed_seconds: float | None,
    trades_placed: int | None,
    wins: int | None,
    losses: int | None,
) -> str | None:
    if elapsed_seconds is None or trades_placed is None:
        return None
    w = int(wins or 0)
    l = int(losses or 0)
    decided = w + l
    if decided > 0:
        rate = 100.0 * w / float(decided)
        wr = f"{rate:.0f}% ({w}W/{l}L)"
    else:
        wr = "— (no settled yet)"
    return (
        f"Session: elapsed={_format_elapsed(float(elapsed_seconds))}"
        f"  trades={int(trades_placed)}"
        f"  win rate={wr}"
    )


def format_trade_line(
    payload: dict[str, Any],
    *,
    session: dict[str, Any] | None = None,
) -> Text:
    decision = str(payload.get("decision") or "NO_TRADE")
    if decision in {"BUY_UP", "BUY_DOWN"}:
        side = "UP" if decision == "BUY_UP" else "DOWN"
        style = "bold green" if side == "UP" else "bold red"
        bet = _bet_usd(payload)
        if side == "UP":
            headline = "PAPER TRADE PLACED — BUY UP"
            meaning = "Betting BTC finishes ABOVE the Kalshi strike (YES)"
        else:
            headline = "PAPER TRADE PLACED — BUY DOWN"
            meaning = "Betting BTC finishes BELOW the Kalshi strike (NO)"
        lines = [
            headline,
            meaning,
            f"Amount bet: ${bet:,.2f}",
        ]
        why = payload.get("why") if isinstance(payload.get("why"), dict) else None
        if why is None and decision in {"BUY_UP", "BUY_DOWN"}:
            why = build_trade_rationale(payload)
        if why:
            lead = str(why.get("lead") or why.get("summary") or "").strip()
            if lead:
                lines.append("")
                lines.append("Why")
                lines.append(f"  {lead}")
            for bullet in why.get("bullets") or []:
                text = str(bullet).strip()
                if text:
                    lines.append(f"  • {text}")
            link_rows = [ln for ln in (why.get("links") or []) if isinstance(ln, dict)]
            if link_rows:
                lines.append("  Links")
                for link in link_rows[:5]:
                    label = str(link.get("label") or "").strip()
                    url = str(link.get("url") or "").strip()
                    if label:
                        lines.append(f"    • {label}")
                    if url:
                        lines.append(f"      {url}")
        sess = session or {}
        session_line = _session_banner_line(
            elapsed_seconds=sess.get("elapsed_seconds"),
            trades_placed=sess.get("trades_placed"),
            wins=sess.get("wins"),
            losses=sess.get("losses"),
        )
        if session_line:
            lines.append(session_line)
        banner = format_banner(lines, style=style)
        detail = Text()
        detail.append(f"[{_ts()}] ", style="dim")
        detail.append(f"#{payload.get('trade_id')}  ", style="dim")
        detail.append(
            f"entry={float(payload.get('entry_price') or 0):.2f}"
            f"  contracts={float(payload.get('size') or 0):.1f}"
            f"  edge={float(payload.get('edge') or 0):+.3f}",
            style="white",
        )
        bank = payload.get("bankroll") if isinstance(payload.get("bankroll"), dict) else {}
        if bank:
            detail.append(f"  cash left=${float(bank.get('cash') or 0):,.2f}", style="dim")
        if payload.get("slug"):
            detail.append(f"\n         market={payload.get('slug')}", style="dim")
        detail.append("\n\n")
        banner.append_text(detail)
        return banner

    line = Text()
    line.append(f"[{_ts()}] ", style="dim")
    line.append("SKIP  ", style="dim")
    line.append(decision, style="yellow")
    line.append(f"  {payload.get('reason') or ''}", style="dim")
    if payload.get("slug"):
        line.append(f"  {payload.get('slug')}", style="dim")
    return line


def format_outcome_line(trade: dict[str, Any]) -> Text:
    won = bool(trade.get("won"))
    side = str(trade.get("side") or "").upper()
    style = "bold green" if won else "bold red"
    pnl = float(trade.get("pnl") or 0.0)
    side_words = "UP (above strike)" if side == "UP" else "DOWN (below strike)"
    if won:
        lines = [
            "RESULT — YOU WON THIS TRADE",
            f"Your side {side_words} was correct",
            f"Profit: ${pnl:+,.2f}",
        ]
    else:
        lines = [
            "RESULT — YOU LOST THIS TRADE",
            f"Your side {side_words} was wrong",
            f"Loss: ${pnl:+,.2f}",
        ]
    if trade.get("size") is not None and trade.get("entry_price") is not None:
        lines.append(f"Original bet: ${_bet_usd(trade):,.2f}")
    banner = format_banner(lines, style=style)
    detail = Text()
    detail.append(f"[{_ts()}] ", style="dim")
    detail.append(f"#{trade.get('trade_id')}  ", style="dim")
    if trade.get("slug"):
        detail.append(f"market={trade.get('slug')}", style="dim")
    detail.append("\n\n")
    banner.append_text(detail)
    return banner


def format_market_tick(tick: dict[str, Any]) -> Text:
    """Green UP / red DOWN lean from Kalshi YES/NO mids; book open/closed."""
    lean = str(tick.get("lean") or "—")
    p_up = float(tick.get("p_up") or 0.5)
    line = Text()
    line.append(f"[{_ts()}] ", style="dim")
    line.append("TICK  ", style="dim")
    if lean == "UP":
        line.append("UP", style="bold green")
    elif lean == "DOWN":
        line.append("DOWN", style="bold red")
    else:
        line.append(lean, style="yellow")
    line.append(f"  P(Up)={p_up * 100:.1f}%", style="bold green" if p_up >= 0.5 else "bold red")
    if tick.get("p_down") is not None:
        p_down = float(tick["p_down"])
        line.append(f"  P(Down)={p_down * 100:.1f}%", style="bold red" if p_down >= 0.5 else "dim")
    if tick.get("book_open") is True:
        line.append("  BOOK OPEN", style="bold green")
    elif tick.get("book_open") is False:
        line.append("  BOOK CLOSED", style="bold red")
    left = tick.get("seconds_left")
    if left is not None:
        line.append(f"  {int(left)}s left", style="dim")
    if tick.get("slug"):
        line.append(f"  {tick['slug']}", style="dim")
    if tick.get("gate_reason") and tick.get("book_open") is False:
        line.append(f"  ({tick['gate_reason']})", style="yellow")
    if tick.get("error"):
        line.append(f"  {tick['error']}", style="yellow")
    return line


def format_window_summary(stats: dict[str, Any]) -> list[Text]:
    """Color-coded end-of-window paper summary lines."""
    net = float(stats.get("net_pnl") or 0.0)
    bet = float(stats.get("bet_usd") or 0.0)
    gained = float(stats.get("gained_usd") or 0.0)
    lost = float(stats.get("lost_usd") or 0.0)
    wins = int(stats.get("wins") or 0)
    losses = int(stats.get("losses") or 0)
    open_n = int(stats.get("open") or 0)
    trades = int(stats.get("trades") or 0)
    net_style = "bold green" if net > 0 else ("bold red" if net < 0 else "bold yellow")

    lines: list[Text] = []
    head = Text()
    head.append(f"[{_ts()}] ", style="dim")
    head.append("WINDOW ", style="bold cyan")
    head.append(str(stats.get("slug") or "—"), style="white")
    if stats.get("winner"):
        w = str(stats["winner"])
        head.append("  resolved ", style="dim")
        head.append(w, style="bold green" if w == "UP" else "bold red")
    lines.append(head)

    body = Text()
    body.append("         ", style="dim")
    body.append(f"bet ${bet:,.2f}", style="white")
    body.append("  gained ", style="dim")
    body.append(f"${gained:,.2f}", style="bold green")
    body.append("  lost ", style="dim")
    body.append(f"${lost:,.2f}", style="bold red")
    body.append("  net ", style="dim")
    body.append(f"${net:+,.2f}", style=net_style)
    lines.append(body)

    foot = Text()
    foot.append("         ", style="dim")
    foot.append(f"{trades} trades  {wins}W/{losses}L", style="dim")
    if open_n:
        foot.append(f"  {open_n} still open", style="yellow")
    if stats.get("cash") is not None:
        foot.append(f"  cash ${float(stats['cash']):,.2f}", style="dim")
    lines.append(foot)
    return lines


def fetch_market_tick(settings: Settings) -> dict[str, Any]:
    """Live Kalshi lean for the active 15m BTC up/down window."""
    fallback_slug = settings.kalshi.series_ticker
    try:
        market = resolve_active_market(settings)
        odds = fetch_market_odds(settings, market)
        slug = odds.slug or market.slug or fallback_slug
        p_up = float(odds.p_up_mid)
        p_down = float(odds.p_down_mid)
        lean = "UP" if p_up >= p_down else "DOWN"
        gate = evaluate_trading_gate(
            market.raw,
            order_min_size=settings.kalshi.order_min_size,
        )
        seconds_left = gate.seconds_left
        if seconds_left is None and market.end_ts is not None:
            seconds_left = max(0, int((to_utc(market.end_ts) - utcnow()).total_seconds()))
        return {
            "slug": slug,
            "market_id": odds.market_id,
            "p_up": p_up,
            "p_down": p_down,
            "lean": lean,
            "seconds_left": seconds_left,
            "book_open": gate.ok,
            "gate_reason": gate.reason,
            "error": None,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "slug": fallback_slug,
            "market_id": None,
            "p_up": 0.5,
            "p_down": 0.5,
            "lean": "—",
            "seconds_left": None,
            "book_open": False,
            "gate_reason": "tick_failed",
            "error": f"tick_failed:{exc}",
        }


def _market_ids_for_slug(session: Session, slug: str) -> set[str]:
    ids = {slug}
    row = session.scalar(select(PolymarketMarket).where(PolymarketMarket.slug == slug))
    if row is not None:
        ids.add(row.market_id)
    return ids


def window_paper_stats(session: Session, settings: Settings, slug: str) -> dict[str, Any]:
    """Bet / gained / lost / net for one market window."""
    ids = _market_ids_for_slug(session, slug)
    trades = list(
        session.scalars(
            select(PaperTrade).where(
                PaperTrade.market_id.in_(ids),
                PaperTrade.decision.in_(("BUY_UP", "BUY_DOWN")),
            )
        ).all()
    )
    bet = 0.0
    gained = 0.0
    lost = 0.0
    net = 0.0
    wins = 0
    losses = 0
    open_n = 0
    winner = None
    for t in trades:
        cost = float(t.size) * float(t.entry_price) + float(t.fees or 0.0) + float(t.slippage or 0.0)
        bet += cost
        if t.pnl is None:
            open_n += 1
            continue
        pnl = float(t.pnl)
        net += pnl
        if pnl > 0:
            gained += pnl
            wins += 1
        elif pnl < 0:
            lost += abs(pnl)
            losses += 1
        # Infer winner from first settled trade side vs win
        if winner is None and t.exit_price is not None:
            side = (t.side or "").upper() or ("UP" if t.decision == "BUY_UP" else "DOWN")
            if pnl > 0:
                winner = side
            elif pnl < 0:
                winner = "DOWN" if side == "UP" else "UP"

    bank = get_bankroll(session, settings)
    return {
        "slug": slug,
        "trades": len(trades),
        "bet_usd": bet,
        "gained_usd": gained,
        "lost_usd": lost,
        "net_pnl": net,
        "wins": wins,
        "losses": losses,
        "open": open_n,
        "winner": winner,
        "cash": bank.get("cash"),
    }


def _format_elapsed(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}h {minutes:02d}m {secs:02d}s"
    if minutes:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"


def format_session_line(
    *,
    elapsed_seconds: float,
    trades_placed: int,
    wins: int,
    losses: int,
) -> Text:
    decided = wins + losses
    if decided > 0:
        rate = 100.0 * wins / float(decided)
        wr = f"{rate:.0f}% ({wins}W/{losses}L)"
    else:
        wr = "— (no settled trades yet)"
    line = Text()
    line.append(f"[{_ts()}] ", style="dim")
    line.append("SESSION  ", style="bold cyan")
    line.append(
        f"elapsed={_format_elapsed(elapsed_seconds)}"
        f"  trades={trades_placed}"
        f"  win rate={wr}",
        style="white",
    )
    return line


def print_run_header(
    console: Console,
    settings: Settings,
    *,
    interval: int,
    trades_only: bool,
) -> None:
    console.print()
    console.print(
        f"[bold]btcpoly run[/bold]  "
        f"[cyan]Kalshi {settings.kalshi.market_duration_minutes}m[/cyan]  "
        f"{settings.kalshi.series_ticker}  "
        f"[dim]tick={interval}s  "
        f"{'trades-only' if trades_only else 'all decisions'}  Ctrl+C to stop[/dim]"
    )
    console.print(
        f"[dim]Markets: "
        f"https://kalshi.com/markets/{settings.kalshi.series_ticker.lower()}[/dim]"
    )
    console.print(
        "[dim]Every tick: market UP/DOWN lean. On each paper trade: session "
        "elapsed / trades / win rate inside the banner. "
        "Model uses post consensus + mention volume.[/dim]"
    )
    console.print()


def _print_window_summary(console: Console, settings: Settings, slug: str) -> dict[str, Any]:
    with session_scope() as session:
        stats = window_paper_stats(session, settings, slug)
    for line in format_window_summary(stats):
        console.print(line)
    console.print()
    return stats


def run_paper_loop(
    settings: Settings,
    *,
    console: Console,
    interval_seconds: int = 10,
    trades_only: bool = False,
    should_stop: Callable[[], bool] | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
    max_cycles: int | None = None,
    run_session: PaperSessionState | None = None,
    reset_on_start: bool | None = None,
    wait_next_window: bool | None = None,
) -> dict[str, Any]:
    """Execute + settle on a tick; print market lean and end-of-window summaries."""
    print_run_header(
        console,
        settings,
        interval=interval_seconds,
        trades_only=trades_only,
    )
    if run_session is None:
        console.print()
        run_session = begin_paper_session(
            settings,
            console=console,
            reset=reset_on_start,
            wait_next_window=wait_next_window,
        )
        console.print()
    session_started = run_session.started_at
    cycles = 0
    trades_seen = 0
    outcomes_seen = 0
    session_wins = 0
    session_losses = 0
    windows_summarized = 0
    active_slug: str | None = None
    summarized: set[str] = set()

    while True:
        if should_stop is not None and should_stop():
            break
        if max_cycles is not None and cycles >= max_cycles:
            break

        cycles += 1
        tick = fetch_market_tick(settings)
        console.print(format_market_tick(tick))
        current_slug = tick.get("slug")

        # Window rolled → summarize the previous one (after settle below).
        rolled_from = None
        if (
            active_slug
            and current_slug
            and current_slug != active_slug
            and active_slug not in summarized
        ):
            rolled_from = active_slug

        payload = execute_paper(settings, run_session=run_session)
        payload["market_duration_minutes"] = settings.kalshi.market_duration_minutes
        with session_scope() as session:
            payload["paper_stats"] = paper_pnl_stats(session)

        decision = str(payload.get("decision") or "NO_TRADE")
        if decision in {"BUY_UP", "BUY_DOWN"}:
            trades_seen += 1
            elapsed = (utcnow() - session_started).total_seconds()
            console.print(
                format_trade_line(
                    payload,
                    session={
                        "elapsed_seconds": elapsed,
                        "trades_placed": trades_seen,
                        "wins": session_wins,
                        "losses": session_losses,
                    },
                )
            )
        elif not trades_only:
            console.print(format_trade_line(payload))

        settled = settle_paper_trades(settings)
        settled_slugs: set[str] = set()
        for trade in settled.get("trades") or []:
            outcomes_seen += 1
            if trade.get("won"):
                session_wins += 1
            else:
                session_losses += 1
            console.print(format_outcome_line(trade))
            if trade.get("slug"):
                settled_slugs.add(str(trade["slug"]))

        # Prefer slug from execute if tick failed.
        if payload.get("slug"):
            current_slug = str(payload["slug"])

        to_summarize: list[str] = []
        if rolled_from:
            to_summarize.append(rolled_from)
        for slug in settled_slugs:
            if slug != current_slug and slug not in summarized:
                to_summarize.append(slug)
        # Also summarize when this window fully settled and time is up.
        left = tick.get("seconds_left")
        if (
            current_slug
            and left is not None
            and int(left) <= 0
            and current_slug not in summarized
            and current_slug in settled_slugs
        ):
            to_summarize.append(current_slug)

        for slug in dict.fromkeys(to_summarize):
            if slug in summarized:
                continue
            _print_window_summary(console, settings, slug)
            summarized.add(slug)
            windows_summarized += 1

        if current_slug:
            active_slug = current_slug

        if should_stop is not None and should_stop():
            break
        if max_cycles is not None and cycles >= max_cycles:
            break
        sleep_fn(max(1, int(interval_seconds)))

    decided = session_wins + session_losses
    win_rate = (session_wins / float(decided)) if decided else None
    return {
        "cycles": cycles,
        "trades_seen": trades_seen,
        "outcomes_seen": outcomes_seen,
        "session_wins": session_wins,
        "session_losses": session_losses,
        "session_win_rate": win_rate,
        "elapsed_seconds": (utcnow() - session_started).total_seconds(),
        "windows_summarized": windows_summarized,
        "duration_minutes": settings.kalshi.market_duration_minutes,
    }
