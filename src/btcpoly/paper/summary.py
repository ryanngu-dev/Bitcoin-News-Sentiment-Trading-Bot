"""Human-readable paper decision summary."""

from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.table import Table
from rich.text import Text

from btcpoly.paper.rationale import clickable_url


def _pct(value: Any) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value) * 100:.1f}%"
    except (TypeError, ValueError):
        return "—"


def _money(value: Any) -> str:
    if value is None:
        return "—"
    try:
        return f"${float(value):,.2f}"
    except (TypeError, ValueError):
        return "—"


def _num(value: Any, digits: int = 3) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return "—"


def _signed_style(value: float, *, invert: bool = False) -> str:
    """Green = good/up, red = bad/down. invert=True flips (rarely needed)."""
    if value > 0:
        return "red" if invert else "bold green"
    if value < 0:
        return "bold green" if invert else "bold red"
    return "dim"


def _colored_pct_vs_half(value: Any) -> Text:
    """P(Up): above 50% green, below 50% red."""
    if value is None:
        return Text("—", style="dim")
    try:
        x = float(value)
    except (TypeError, ValueError):
        return Text("—", style="dim")
    return Text(_pct(x), style=_signed_style(x - 0.5))


def _colored_signed_pct(value: Any, *, digits: int = 3) -> Text:
    if value is None:
        return Text("—", style="dim")
    try:
        x = float(value)
    except (TypeError, ValueError):
        return Text("—", style="dim")
    return Text(f"{x * 100:+.{digits}f}%", style=_signed_style(x))


def _colored_edge(value: Any) -> Text:
    if value is None:
        return Text("—", style="dim")
    try:
        x = float(value)
    except (TypeError, ValueError):
        return Text("—", style="dim")
    return Text(f"{x:+.3f}", style=_signed_style(x))


def _rainbow(text: str) -> Text:
    """Silly multi-color label for Live ARMED."""
    colors = ("red", "yellow", "green", "cyan", "blue", "magenta")
    out = Text()
    for i, ch in enumerate(text):
        out.append(ch, style=f"bold {colors[i % len(colors)]}")
    return out


def _scoreboard_line(stats: dict[str, Any] | None) -> Text | None:
    if not stats:
        return None
    pnl = float(stats.get("pnl_total") or 0.0)
    wins = int(stats.get("wins") or 0)
    losses = int(stats.get("losses") or 0)
    open_n = int(stats.get("open") or 0)
    style = "bold green" if pnl > 0 else ("bold red" if pnl < 0 else "dim")
    line = Text()
    line.append("Scoreboard: ", style="dim")
    line.append(f"${pnl:+.2f}", style=style)
    line.append(f"  ({wins}W / {losses}L", style="dim")
    if open_n:
        line.append(f", {open_n} open", style="dim")
    line.append(")", style="dim")
    return line


def _bankroll_line(bankroll: dict[str, Any] | None) -> Text | None:
    if not bankroll:
        return None
    cash = float(bankroll.get("cash") or 0.0)
    line = Text()
    line.append("Cash: ", style="dim")
    line.append(f"${cash:,.2f}", style="bold")
    line.append(
        f"  (start ${float(bankroll.get('starting_cash') or 0):,.0f}, "
        f"settled ${float(bankroll.get('settled_pnl') or 0):+.2f}, "
        f"open ${float(bankroll.get('open_cost') or 0):.2f})",
        style="dim",
    )
    return line


def print_paper_summary(
    console: Console,
    payload: dict[str, Any],
    *,
    paper_stats: dict[str, Any] | None = None,
) -> None:
    """Compact terminal view of a paper execute result."""
    decision = str(payload.get("decision") or "NO_TRADE")
    color = {
        "BUY_UP": "bold green",
        "BUY_DOWN": "bold red",
        "NO_TRADE": "bold yellow",
        "REFUSED": "bold red",
    }.get(decision, "white")

    console.print()
    console.print(f"[{color}]PAPER  {decision}[/{color}]  [dim]{payload.get('reason') or ''}[/dim]")
    console.print()

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("k", style="dim")
    table.add_column("v")

    table.add_row("Market", str(payload.get("slug") or payload.get("market_id") or "—"))
    if payload.get("market_duration_minutes") is not None:
        table.add_row("Window", f"{payload.get('market_duration_minutes')}m")
    table.add_row("Model", str(payload.get("model") or "—"))
    table.add_row("BTC", _money(payload.get("btc_price")))
    if payload.get("btc_ret") is not None:
        table.add_row("BTC 60s move", _colored_signed_pct(payload.get("btc_ret")))
    table.add_row("Kalshi P(Up/YES)", _colored_pct_vs_half(payload.get("p_up_market")))
    table.add_row("Model P(Up)", _colored_pct_vs_half(payload.get("p_up_model")))
    table.add_row("Edge (model − market)", _colored_edge(payload.get("edge")))
    table.add_row("Confidence", _num(payload.get("confidence"), 2))
    table.add_row("Spread", _num(payload.get("spread")))
    feats = payload.get("features") if isinstance(payload.get("features"), dict) else {}
    if feats:
        table.add_row(
            "Attn z900",
            f"{_num(feats.get('attn_z_900'), 2)}  (n300={feats.get('mention_count_300')}, n900={feats.get('mention_count_900')})",
        )
        if feats.get("sentiment_net_900") is not None:
            table.add_row(
                "Post consensus",
                f"net={_num(feats.get('sentiment_net_900'), 2)}  "
                f"(+bull/−bear over 15m posts)",
            )
        if int(feats.get("ai_sentiment_scored_900") or 0) > 0:
            table.add_row(
                "AI lean",
                f"net={_num(feats.get('ai_sentiment_net_900'), 2)}  "
                f"cred={_num(feats.get('ai_credibility_mean_900'), 2)}  "
                f"(n={feats.get('ai_sentiment_scored_900')})",
            )
    if decision in {"BUY_UP", "BUY_DOWN"}:
        side_style = "bold green" if decision == "BUY_UP" else "bold red"
        table.add_row("Paper side", Text(decision.replace("BUY_", ""), style=side_style))
        table.add_row("Paper entry", _num(payload.get("entry_price"), 2))
        table.add_row("Paper size", _num(payload.get("size"), 1))
        if payload.get("fees") or payload.get("slippage"):
            table.add_row(
                "Costs",
                f"fees={_money(payload.get('fees'))}  slip={_money(payload.get('slippage'))}",
            )
    table.add_row("Trade id", str(payload.get("trade_id") or "—"))
    live = payload.get("live_trading_armed")
    table.add_row(
        "Live",
        _rainbow("ARMED") if live else Text("off", style="white"),
    )

    console.print(table)

    bank = _bankroll_line(payload.get("bankroll") if isinstance(payload.get("bankroll"), dict) else None)
    if bank is not None:
        console.print()
        console.print(bank)

    stats = paper_stats if paper_stats is not None else payload.get("paper_stats")
    board = _scoreboard_line(stats if isinstance(stats, dict) else None)
    if board is not None:
        console.print(board)

    sources = payload.get("sources") or []
    console.print()
    used = bool(feats)
    attn_note = "used by model" if used else "display only"
    if sources:
        console.print(f"[bold]Attention context[/bold]  [dim]({len(sources)} recent — {attn_note})[/dim]")
        for item in sources[:5]:
            title = str(item.get("title") or "")[:100]
            plat = str(item.get("platform") or "?").upper()
            url = clickable_url(str(item.get("url") or "").strip() or None, title=title)
            console.print(f"  [cyan]{plat:<8}[/cyan] {title}")
            if url:
                console.print(f"           {url}")
        if len(sources) > 5:
            console.print(f"  [dim]… +{len(sources) - 5} more (btcpoly feed  or  execute --json)[/dim]")
    else:
        console.print("[dim]Attention context: none in DB yet — run btcpoly ingest[/dim]")

    why = payload.get("why") if isinstance(payload.get("why"), dict) else None
    if why and decision in {"BUY_UP", "BUY_DOWN"}:
        console.print()
        console.print("[bold]Why[/bold]")
        lead = str(why.get("lead") or why.get("summary") or "").strip()
        if lead:
            console.print(f"  {lead}")
        for bullet in why.get("bullets") or []:
            text = str(bullet).strip()
            if text:
                console.print(f"  • {text}")
        link_rows = [ln for ln in (why.get("links") or []) if isinstance(ln, dict)]
        if link_rows:
            console.print("  [bold]Links[/bold]")
            for link in link_rows:
                label = str(link.get("label") or "").strip()
                url = str(link.get("url") or "").strip()
                if label:
                    console.print(f"    • {label}")
                if url:
                    # Plain URL on its own line — most terminals make this clickable.
                    console.print(f"      {url}")
    console.print()


def print_settle_summary(console: Console, payload: dict[str, Any]) -> None:
    settled = int(payload.get("settled") or 0)
    wins = int(payload.get("wins") or 0)
    losses = int(payload.get("losses") or 0)
    pnl = float(payload.get("pnl_total") or 0.0)
    style = "bold green" if pnl > 0 else ("bold red" if pnl < 0 else "yellow")
    console.print()
    console.print(
        f"[bold]SETTLE[/bold]  settled={settled}  "
        f"[{style}]${pnl:+.2f}[/{style}]  ({wins}W / {losses}L)"
    )
    skipped = []
    if payload.get("skipped_open"):
        skipped.append(f"open={payload['skipped_open']}")
    if payload.get("skipped_unresolved"):
        skipped.append(f"unresolved={payload['skipped_unresolved']}")
    if payload.get("skipped_no_market"):
        skipped.append(f"no_market={payload['skipped_no_market']}")
    if skipped:
        console.print(f"[dim]Skipped: {', '.join(skipped)}[/dim]")
    bank = _bankroll_line(payload.get("bankroll") if isinstance(payload.get("bankroll"), dict) else None)
    if bank is not None:
        console.print(bank)
    board = _scoreboard_line(payload.get("paper_stats") if isinstance(payload.get("paper_stats"), dict) else None)
    if board is not None:
        console.print(board)
    console.print()
