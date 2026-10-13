from __future__ import annotations

import json
import sys
import threading
import time

import click
from rich.console import Console
from rich.table import Table
from sqlalchemy import desc, select

from btcpoly import __version__
from btcpoly.config import REPO_ROOT, Settings, load_settings
from btcpoly.db.models import Metric, PaperTrade, RawPostRow
from btcpoly.db.session import count_rows, init_db, session_scope, table_names
from btcpoly.exit_codes import EXIT_HARD, EXIT_OK, EXIT_USAGE
from btcpoly.ingestion.agent_reach.doctor import check_agent_reach
from btcpoly.ingestion.pipeline import IngestSummary, run_ingest, run_live_channel_loops
from btcpoly.ingestion.kalshi.mode import with_market_duration
from btcpoly.live.execution import LiveTradingDisabledError, assert_live_trading_allowed, place_order
from btcpoly.logging import configure_logging
from btcpoly.monitoring.feed import (
    SourceHeadline,
    headline_key,
    print_source_feed,
    recent_headlines,
    render_source_line,
    sort_headlines,
)
from btcpoly.paper.bankroll import get_bankroll
from btcpoly.paper.execute import execute_paper
from btcpoly.paper.run_loop import run_paper_loop
from btcpoly.paper.settle import paper_pnl_stats, settle_paper_trades
from btcpoly.paper.summary import print_paper_summary, print_settle_summary

console = Console()

_DURATION = click.Choice(["15"], case_sensitive=False)


def _load(config: str | None, *, duration: int | str | None = None) -> Settings:
    settings = load_settings(config)
    if duration is not None:
        settings = with_market_duration(settings, int(duration))
    configure_logging(settings)
    return settings


def _wants_json(ctx: click.Context, json_out: bool) -> bool:
    return bool(json_out or (ctx.obj or {}).get("json_mode"))


def _emit(ctx: click.Context, payload: dict, json_out: bool, human: object) -> None:
    if _wants_json(ctx, json_out):
        click.echo(json.dumps(payload, indent=2, default=str))
    else:
        human()  # type: ignore[operator]


@click.group()
@click.option("--json", "json_mode", is_flag=True, help="Machine-readable JSON on stdout.")
@click.version_option(__version__)
@click.pass_context
def main(ctx: click.Context, json_mode: bool) -> None:
    """BTC Kalshi attention lab (research / paper first)."""
    ctx.ensure_object(dict)
    ctx.obj["json_mode"] = json_mode


@main.command()
@click.pass_context
@click.option("--config", type=click.Path(exists=True, dir_okay=False), default=None)
@click.option("--json", "json_out", is_flag=True)
@click.option("--json-out", "json_out_alias", is_flag=True, help="Alias for --json.")
def doctor(ctx: click.Context, config: str | None, json_out: bool, json_out_alias: bool) -> None:
    """Check config, database, kill switch, and Agent Reach health."""
    settings = _load(config)
    engine = init_db(settings)
    reach = check_agent_reach(settings)
    payload = {
        "version": __version__,
        "live_trading_enabled_in_config": settings.execution.enabled,
        "live_trading_armed": settings.live_trading_armed,
        "database_url": str(engine.url),
        "tables": table_names(engine),
        "kalshi_duration_minutes": settings.kalshi.market_duration_minutes,
        "kalshi_series": settings.kalshi.series_ticker,
        "exchange": "kalshi",
        "agent_reach": reach.to_dict(),
        "exit_code": EXIT_OK,
    }

    def human() -> None:
        console.print(f"[bold]btcpoly[/bold] {__version__} doctor")
        console.print(f"Live trading armed: [red]{settings.live_trading_armed}[/red]")
        console.print(f"Database: {engine.url}")
        console.print(f"Tables: {len(payload['tables'])}")
        if reach.installed:
            style = "green" if reach.ok else "yellow"
            console.print(f"Agent Reach: [{style}]{reach.message}[/{style}] ({reach.executable})")
            if reach.channels:
                table = Table(title="Agent Reach channels")
                table.add_column("channel")
                table.add_column("detail")
                for name, detail in reach.channels.items():
                    table.add_row(str(name), json.dumps(detail, default=str)[:80])
                console.print(table)
        else:
            console.print(f"[yellow]Agent Reach: {reach.message}[/yellow]")

    _emit(ctx, payload, json_out or json_out_alias, human)


@main.command()
@click.pass_context
@click.option("--config", type=click.Path(exists=True, dir_okay=False), default=None)
@click.option("--once", is_flag=True, help="One poll then exit (agent default).")
@click.option("--loop", "loop_mode", is_flag=True, help="Poll forever (default in the terminal).")
@click.option("--dry-run", is_flag=True, help="List channels; do not fetch or write.")
@click.option("--interval", type=int, default=None, help="Seconds to wait after each poll. 0 = immediately again.")
@click.option("--channels", default=None, help="Comma-separated channel subset.")
@click.option("--json", "json_out", is_flag=True)
def ingest(
    ctx: click.Context,
    config: str | None,
    once: bool,
    loop_mode: bool,
    dry_run: bool,
    interval: int | None,
    channels: str | None,
    json_out: bool,
) -> None:
    """Poll attention sources and persist raw posts."""
    if sum([bool(once), bool(loop_mode), bool(dry_run)]) > 1:
        raise click.ClickException("use only one of --once, --dry-run, --loop")
    settings = _load(config)
    init_db(settings)
    selected = [c.strip() for c in channels.split(",")] if channels else None
    json_mode = _wants_json(ctx, json_out)
    if not once and not loop_mode and not dry_run:
        if json_mode:
            once = True
        else:
            loop_mode = True

    def one_shot(on_channel=None) -> IngestSummary:
        return run_ingest(settings, dry_run=dry_run, channels=selected, on_channel=on_channel)

    def show(summary: IngestSummary, *, looping: bool = False, wait: int = 0) -> None:
        def human() -> None:
            stamp = summary.ingested_at.strftime("%Y-%m-%d %H:%M:%S UTC")
            label = "dry-run" if summary.dry_run else "ingest"
            console.print(f"[bold]{label}[/bold] {stamp}  fetched={summary.fetched} inserted={summary.inserted} dupes={summary.duplicates}")
            for row in summary.channels:
                if row.skipped:
                    console.print(f"  skip {row.channel}: {row.skipped}")
                elif row.error:
                    console.print(f"  error {row.channel}: {row.error}")
                else:
                    console.print(
                        f"  {row.channel}: fetched={row.fetched} inserted={row.inserted} dupes={row.duplicates}"
                    )
            print_source_feed(console, summary.sources, heading="BTC mentions this poll")
            if not looping and not summary.dry_run:
                console.print("\n[dim]One-shot poll. Live ticker: btcpoly ingest[/dim]")

        _emit(ctx, summary.to_dict(), json_out, human)

    def show_live(summary: IngestSummary, *, seen: set[str], banner_shown: list[bool]) -> int:
        if not banner_shown[0]:
            skipped = [row for row in summary.channels if row.skipped]
            if skipped:
                bits = ", ".join(f"{row.channel}" for row in skipped)
                console.print(f"[dim]Not connected yet: {bits}[/dim]")
            banner_shown[0] = True
            console.print()
        added = 0
        for item in sort_headlines(summary.sources, newest_first=False):
            key = headline_key(item)
            if key in seen:
                continue
            seen.add(key)
            console.print(render_source_line(item))
            added += 1
        return added

    if loop_mode:
        wait = interval if interval is not None else settings.ingest.interval_seconds
        if json_mode:
            while True:
                try:
                    summary = one_shot()
                except Exception as exc:
                    console.print(f"[red]ingest failed: {exc}[/red]")
                    ctx.exit(EXIT_HARD)
                show(summary, looping=True, wait=wait)
                time.sleep(max(0, wait))
            return
        try:
            sys.stdout.reconfigure(line_buffering=True)
        except Exception:
            pass
        names = selected or list(settings.agent_reach.channels)
        console.print("[bold]BTC live mentions[/bold]  Ctrl+C to stop")
        console.print(
            f"[dim]Channels running in parallel: {', '.join(names)}. "
            "Each source re-polls on its own (slow Twitter won't block RSS).[/dim]"
        )
        console.file.flush()
        seen: set[str] = set()
        banner_shown = [False]
        print_lock = threading.Lock()

        def on_summary(summary: IngestSummary) -> None:
            with print_lock:
                if not banner_shown[0]:
                    skipped = [row for row in summary.channels if row.skipped]
                    if skipped:
                        bits = ", ".join(row.channel for row in skipped)
                        console.print(f"[dim]Not connected yet: {bits}[/dim]")
                    banner_shown[0] = True
                    console.print()
                for item in sort_headlines(summary.sources, newest_first=False):
                    key = headline_key(item)
                    if key in seen:
                        continue
                    seen.add(key)
                    console.print(render_source_line(item))

        try:
            run_live_channel_loops(
                settings,
                channels=selected,
                interval_seconds=wait,
                on_summary=on_summary,
            )
        except KeyboardInterrupt:
            console.print("\n[dim]ingest stopped[/dim]")
            # Soft exit so pending collector threads don't dump atexit join noise.
            ctx.exit(0)
        return

    try:
        summary = one_shot()
    except Exception as exc:
        payload = {"error": str(exc), "exit_code": EXIT_HARD}

        def human_err() -> None:
            console.print(f"[red]ingest failed: {exc}[/red]")

        _emit(ctx, payload, json_out, human_err)
        ctx.exit(EXIT_HARD)
    show(summary, looping=False)
    ctx.exit(summary.exit_code())


@main.command()
@click.pass_context
@click.option("--config", type=click.Path(exists=True, dir_okay=False), default=None)
@click.option("--duration", type=_DURATION, default=None, help="Kalshi BTC window minutes (15 only).")
@click.option("--json", "json_out", is_flag=True)
def status(ctx: click.Context, config: str | None, duration: str | None, json_out: bool) -> None:
    """Runtime snapshot: config, DB, kill switch, counts."""
    from btcpoly.db.models import BtcTick, PolymarketBook, PolymarketMarket

    settings = _load(config, duration=duration)
    engine = init_db(settings)
    last_ingest = None
    headlines = []
    last_spot = None
    last_market = None
    last_book = None
    with session_scope() as session:
        metric = session.scalars(
            select(Metric).where(Metric.name == "ingest_run").order_by(desc(Metric.id))
        ).first()
        if metric is not None:
            last_ingest = metric.extra
        headlines = recent_headlines(session, settings, limit=15)
        stats = paper_pnl_stats(session)
        bankroll = get_bankroll(session, settings)
        tick = session.scalars(select(BtcTick).order_by(desc(BtcTick.id))).first()
        if tick is not None:
            last_spot = {
                "price": tick.price,
                "source": tick.source,
                "event_ts": tick.event_ts.isoformat() if tick.event_ts else None,
            }
        mkt = session.scalars(select(PolymarketMarket).order_by(desc(PolymarketMarket.id))).first()
        if mkt is not None:
            last_market = {
                "market_id": mkt.market_id,
                "slug": mkt.slug,
                "question": mkt.question,
                "status": mkt.status,
            }
        book = session.scalars(select(PolymarketBook).order_by(desc(PolymarketBook.id))).first()
        if book is not None:
            mid = None
            if book.best_bid is not None and book.best_ask is not None:
                mid = (book.best_bid + book.best_ask) / 2.0
            last_book = {
                "market_id": book.market_id,
                "token_id": book.token_id,
                "best_bid": book.best_bid,
                "best_ask": book.best_ask,
                "mid": mid,
                "spread": book.spread,
            }
    current_slug = settings.kalshi.series_ticker
    payload = {
        "version": __version__,
        "config_root": str(REPO_ROOT),
        "hypothesis": settings.hypothesis,
        "exchange": "kalshi",
        "market": settings.kalshi.series_ticker,
        "market_duration_minutes": settings.kalshi.market_duration_minutes,
        "current_slug": current_slug,
        "btc_spot": last_spot,
        "kalshi_market": last_market,
        "kalshi_book": last_book,
        "risk": {
            "min_edge": settings.risk.min_edge,
            "min_confidence": settings.risk.min_confidence,
            "max_spread": settings.risk.max_spread,
            "max_position_usd": settings.risk.max_position_usd,
            "max_bankroll_pct": settings.risk.max_bankroll_pct,
        },
        "paper": {
            "starting_cash": settings.paper.starting_cash,
            "fee_bps": settings.paper.fee_bps,
            "slippage_bps": settings.paper.slippage_bps,
            "model_name": settings.paper.model_name,
        },
        "bankroll": bankroll,
        "database_url": str(engine.url),
        "tables": table_names(engine),
        "raw_posts": count_rows(RawPostRow, engine),
        "paper_trades": count_rows(PaperTrade, engine),
        "paper_stats": stats,
        "live_trading_armed": settings.live_trading_armed,
        "last_ingest": last_ingest,
        "sources": [item.to_dict() for item in headlines],
    }

    def human() -> None:
        console.print(f"[bold]btcpoly[/bold] {__version__}")
        console.print(f"Config root: {REPO_ROOT}")
        console.print(f"Exchange: Kalshi")
        console.print(f"Market: {settings.kalshi.series_ticker} ({settings.kalshi.market_duration_minutes}m)")
        console.print(f"Series: {current_slug}")
        console.print(f"Model: {settings.paper.model_name}")
        if last_spot:
            console.print(f"BTC spot: {last_spot['price']} ({last_spot['source']})")
        else:
            console.print("BTC spot: [dim]none yet — run execute --mode paper[/dim]")
        if last_market:
            console.print(f"Kalshi: {last_market.get('slug') or last_market.get('market_id')}")
        if last_book and last_book.get("mid") is not None:
            console.print(f"Last book mid: {last_book['mid']:.3f} spread={last_book.get('spread')}")
        console.print(f"DB: {engine.url}")
        console.print(f"raw_posts: {payload['raw_posts']}  paper_trades: {payload['paper_trades']}")
        cash = float(bankroll.get("cash") or 0.0)
        console.print(
            f"Paper cash: [bold]${cash:,.2f}[/bold]  "
            f"(start ${bankroll.get('starting_cash', 0):,.0f}, "
            f"settled ${float(bankroll.get('settled_pnl') or 0):+.2f}, "
            f"open ${float(bankroll.get('open_cost') or 0):.2f})"
        )
        pnl = float(stats.get("pnl_total") or 0.0)
        pnl_style = "green" if pnl > 0 else ("red" if pnl < 0 else "dim")
        console.print(
            f"Paper scoreboard: [{pnl_style}]${pnl:+.2f}[/{pnl_style}]  "
            f"({stats.get('wins', 0)}W / {stats.get('losses', 0)}L, {stats.get('open', 0)} open)"
        )
        console.print(
            "Live trading: "
            + ("[red]ARMED[/red]" if settings.live_trading_armed else "[green]DISABLED[/green]")
        )
        console.print("Agents: btcpoly execute --mode paper --json ; btcpoly settle --json")
        print_source_feed(console, headlines, heading="Recent BTC sources")

    _emit(ctx, payload, json_out, human)

@main.command("feed")
@click.pass_context
@click.option("--config", type=click.Path(exists=True, dir_okay=False), default=None)
@click.option("--limit", type=int, default=20, show_default=True)
@click.option("--json", "json_out", is_flag=True)
def feed_cmd(ctx: click.Context, config: str | None, limit: int, json_out: bool) -> None:
    """Show recent BTC mentions, color-coded by source (YouTube is red)."""
    settings = _load(config)
    init_db(settings)
    with session_scope() as session:
        headlines = recent_headlines(session, settings, limit=max(1, limit))
    payload = {"sources": [item.to_dict() for item in headlines], "count": len(headlines)}

    def human() -> None:
        print_source_feed(console, headlines, heading="BTC mentions by source")

    _emit(ctx, payload, json_out, human)


@main.command("execute")
@click.pass_context
@click.option("--config", type=click.Path(exists=True, dir_okay=False), default=None)
@click.option(
    "--mode",
    type=click.Choice(["paper", "live"], case_sensitive=False),
    required=True,
    help="paper now; live only after profitability + kill switch.",
)
@click.option("--duration", type=_DURATION, default=None, help="Kalshi BTC window minutes (15 only).")
@click.option("--json", "json_out", is_flag=True)
def execute_cmd(
    ctx: click.Context,
    config: str | None,
    mode: str,
    duration: str | None,
    json_out: bool,
) -> None:
    """Paper (now) or live (later) execution. Same interface; live is refused until armed."""
    settings = _load(config, duration=duration)
    init_db(settings)
    mode = mode.lower()
    if mode == "paper":
        payload = execute_paper(settings)
        payload["market_duration_minutes"] = settings.kalshi.market_duration_minutes
        payload["exchange"] = "kalshi"
        with session_scope() as session:
            payload["paper_stats"] = paper_pnl_stats(session)

        def human() -> None:
            print_paper_summary(console, payload)

        _emit(ctx, payload, json_out, human)
        ctx.exit(EXIT_OK)
        return

    try:
        assert_live_trading_allowed(settings)
        place_order(settings=settings)
    except LiveTradingDisabledError as exc:
        payload = {"mode": "live", "error": str(exc), "decision": "REFUSED"}
        _emit(ctx, payload, json_out, lambda: console.print(f"[red]LIVE REFUSED[/red] {exc}"))
        ctx.exit(EXIT_USAGE)
    except NotImplementedError as exc:
        payload = {"mode": "live", "error": str(exc), "decision": "REFUSED"}
        _emit(ctx, payload, json_out, lambda: console.print(f"[red]LIVE NOT IMPLEMENTED[/red] {exc}"))
        ctx.exit(EXIT_HARD)


@main.command("settle")
@click.pass_context
@click.option("--config", type=click.Path(exists=True, dir_okay=False), default=None)
@click.option("--duration", type=_DURATION, default=None, help="Kalshi series duration hint (15).")
@click.option("--json", "json_out", is_flag=True)
def settle_cmd(ctx: click.Context, config: str | None, duration: str | None, json_out: bool) -> None:
    """Settle closed paper BUY_UP/BUY_DOWN trades against Kalshi outcomes."""
    settings = _load(config, duration=duration)
    init_db(settings)
    payload = settle_paper_trades(settings)

    def human() -> None:
        print_settle_summary(console, payload)

    _emit(ctx, payload, json_out, human)
    ctx.exit(EXIT_OK)


@main.command("reset-paper")
@click.pass_context
@click.option("--config", type=click.Path(exists=True, dir_okay=False), default=None)
@click.option("--yes", "confirm", is_flag=True, help="Required: confirm wipe of paper trades.")
@click.option("--json", "json_out", is_flag=True)
def reset_paper_cmd(ctx: click.Context, config: str | None, confirm: bool, json_out: bool) -> None:
    """Wipe paper trades so bankroll returns to starting_cash (default $100)."""
    if not confirm:
        raise click.ClickException("refusing to wipe paper book without --yes")
    settings = _load(config)
    init_db(settings)
    from btcpoly.paper.reset import reset_paper_book

    payload = reset_paper_book(settings)

    def human() -> None:
        cash = float(payload["bankroll"].get("cash") or 0.0)
        console.print(
            f"[bold]PAPER RESET[/bold]  cleared={payload['cleared_paper_trades']} trades  "
            f"cash=[bold]${cash:,.2f}[/bold]  (start ${payload['starting_cash']:,.0f})"
        )

    _emit(ctx, payload, json_out, human)
    ctx.exit(EXIT_OK)


@main.command("run")
@click.pass_context
@click.option("--config", type=click.Path(exists=True, dir_okay=False), default=None)
@click.option(
    "--duration",
    type=_DURATION,
    default="15",
    show_default=True,
    help="Kalshi BTC up/down window (15m only; no 5m on Kalshi).",
)
@click.option(
    "--interval",
    type=int,
    default=10,
    show_default=True,
    help="Seconds between market ticks (UP/DOWN lean + execute/settle).",
)
@click.option(
    "--trades-only",
    is_flag=True,
    help="Only print BUY_* trades and WIN/LOSE outcomes (still shows ticks + window summaries).",
)
@click.option(
    "--no-reset",
    is_flag=True,
    help="Do not wipe paper trades / reset cash when starting this run.",
)
def run_cmd(
    ctx: click.Context,
    config: str | None,
    duration: str,
    interval: int,
    trades_only: bool,
    no_reset: bool,
) -> None:
    """Keep paper trading on Kalshi: boxed UP/DOWN trades and WIN/LOSE."""
    if ctx.obj.get("json"):
        raise click.ClickException("btcpoly run is a human terminal loop; do not use --json")
    settings = _load(config, duration=duration)
    init_db(settings)
    try:
        run_paper_loop(
            settings,
            console=console,
            interval_seconds=max(1, int(interval)),
            trades_only=trades_only,
            reset_on_start=False if no_reset else None,
        )
    except KeyboardInterrupt:
        console.print("\n[dim]Stopped.[/dim]")
    ctx.exit(EXIT_OK)
