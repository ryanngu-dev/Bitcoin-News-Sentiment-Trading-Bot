from __future__ import annotations

import json

from click.testing import CliRunner

from btcpoly.cli import main
from btcpoly.ingestion.pipeline import IngestSummary


def test_ingest_dry_run_lists_channels() -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["ingest", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "dry-run" in result.output
    assert "youtube" in result.output
    assert "twitter" in result.output


def test_ingest_once_prints_refresh_hint(monkeypatch) -> None:
    summary = IngestSummary()
    monkeypatch.setattr("btcpoly.cli.run_ingest", lambda *a, **k: summary)
    runner = CliRunner()
    result = runner.invoke(main, ["ingest", "--once"])
    assert result.exit_code == 0, result.output
    assert "One-shot poll" in result.output
    assert "btcpoly ingest" in result.output


def test_ingest_once_json(monkeypatch) -> None:
    summary = IngestSummary()
    summary.fetched = 3
    summary.inserted = 2
    summary.duplicates = 1
    monkeypatch.setattr("btcpoly.cli.run_ingest", lambda *a, **k: summary)
    runner = CliRunner()
    result = runner.invoke(main, ["ingest", "--once", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["fetched"] == 3
    assert payload["inserted"] == 2
    assert payload["duplicates"] == 1


def test_status_json() -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["status", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["live_trading_armed"] is False
    assert "raw_posts" in payload
    assert "paper_trades" in payload
    assert "current_slug" in payload
    assert payload["current_slug"] == "KXBTC15M"
    assert payload["exchange"] == "kalshi"
    assert "risk" in payload
    assert "paper_stats" in payload
    assert set(payload["paper_stats"]) >= {"open", "settled", "wins", "losses", "pnl_total", "win_rate"}
    assert "bankroll" in payload
    assert payload["bankroll"]["starting_cash"] == 100.0
    assert "cash" in payload["bankroll"]
    assert payload["paper"]["model_name"] == "momentum_attn_v1"


def test_status_duration_15() -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["status", "--duration", "15", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["market_duration_minutes"] == 15
    assert payload["market"] == "KXBTC15M"
    assert payload["current_slug"] == "KXBTC15M"


def test_doctor_json_kill_switch_off() -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["doctor", "--json-out"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["live_trading_armed"] is False
    assert "raw_posts" in payload["tables"]
    assert payload["agent_reach"]["installed"] in {True, False}


def test_status_shows_disabled() -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["status"])
    assert result.exit_code == 0, result.output
    assert "DISABLED" in result.output


def test_execute_paper_json(monkeypatch) -> None:
    from datetime import datetime, timedelta, timezone

    from btcpoly.ingestion.btc_market.spot import SpotSnapshot
    from btcpoly.ingestion.kalshi.markets import MarketOdds, ResolvedMarket, TokenBook
    from btcpoly.timeutil import utcnow

    monkeypatch.setattr(
        "btcpoly.paper.execute.fetch_btc_return",
        lambda settings, window_seconds=60: SpotSnapshot(
            price=80123.0,
            event_ts=datetime.now(tz=timezone.utc),
            source="binance",
            ret=0.0,
            window_seconds=window_seconds,
        ),
    )
    now = utcnow()
    raw = {
        "status": "active",
        "open_time": (now - timedelta(minutes=5)).isoformat().replace("+00:00", "Z"),
        "close_time": (now + timedelta(minutes=10)).isoformat().replace("+00:00", "Z"),
    }
    market = ResolvedMarket(
        market_id="KXBTC15M-CLI",
        slug="KXBTC15M-CLI",
        question="Bitcoin Up or Down",
        up_token_id="YES",
        down_token_id="NO",
        start_ts=None,
        end_ts=None,
        outcome_prices=(0.5, 0.5),
        raw=raw,
    )
    monkeypatch.setattr("btcpoly.paper.execute.resolve_active_market", lambda settings: market)

    def _book(mid: float) -> TokenBook:
        return TokenBook(
            token_id="t",
            best_bid=mid - 0.01,
            best_ask=mid + 0.01,
            mid=mid,
            spread=0.02,
            bids=[],
            asks=[],
        )

    monkeypatch.setattr(
        "btcpoly.paper.execute.fetch_market_odds",
        lambda settings, m: MarketOdds(
            market_id=m.market_id,
            slug=m.slug,
            up=_book(0.5),
            down=_book(0.5),
            p_up_mid=0.5,
            p_down_mid=0.5,
            up_ask=0.51,
            down_ask=0.51,
            spread_up=0.02,
            source="kalshi",
        ),
    )
    runner = CliRunner()
    result = runner.invoke(main, ["execute", "--mode", "paper", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["mode"] == "paper"
    assert payload["decision"] in {"NO_TRADE", "BUY_UP", "BUY_DOWN"}
    assert payload["reason"] != "no_model_yet"
    assert payload["btc_price"] == 80123.0
    assert payload["slug"] == "KXBTC15M-CLI"
    assert isinstance(payload["sources"], list)
    assert "bankroll" in payload
    assert "cash" in payload["bankroll"]
    assert "features" in payload
    assert "attn_z_900" in payload["features"]


def test_settle_json(monkeypatch) -> None:
    monkeypatch.setattr(
        "btcpoly.cli.settle_paper_trades",
        lambda settings: {
            "settled": 1,
            "skipped_open": 0,
            "skipped_unresolved": 0,
            "skipped_no_market": 0,
            "wins": 1,
            "losses": 0,
            "pnl_total": 12.5,
            "trades": [{"trade_id": 1, "won": True, "pnl": 12.5}],
            "paper_stats": {
                "open": 0,
                "settled": 1,
                "wins": 1,
                "losses": 0,
                "pnl_total": 12.5,
                "win_rate": 1.0,
            },
            "event_ts": "2026-08-26T00:00:00+00:00",
        },
    )
    runner = CliRunner()
    result = runner.invoke(main, ["settle", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["settled"] == 1
    assert payload["pnl_total"] == 12.5
    assert payload["paper_stats"]["wins"] == 1

    runner = CliRunner()
    result = runner.invoke(main, ["feed", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert "sources" in payload
    assert payload["count"] == len(payload["sources"])
    runner = CliRunner()
    result = runner.invoke(main, ["execute", "--mode", "live", "--json"])
    assert result.exit_code == 1, result.output
    payload = json.loads(result.output)
    assert payload["mode"] == "live"
    assert payload["decision"] == "REFUSED"
