from __future__ import annotations

from datetime import datetime, timezone

from btcpoly.ingestion.kalshi.markets import expand_ticker_candidates, parse_winner, pick_live_market
from btcpoly.ingestion.kalshi.trading_hours import evaluate_trading_gate


def test_parse_winner_yes_no() -> None:
    assert parse_winner({"result": "yes", "status": "finalized"}) == "UP"
    assert parse_winner({"result": "no", "status": "finalized"}) == "DOWN"
    assert parse_winner({"result": "", "status": "active"}) is None


def test_expand_ticker_from_kalshi_url() -> None:
    url = "https://kalshi.com/markets/kxbtc15m/bitcoin-price-up-down/kxbtc15m-26aug262030"
    cands = expand_ticker_candidates(url)
    assert "KXBTC15M-26AUG262030" in cands
    assert "KXBTC15M-26AUG262030-30" in cands


def test_pick_live_market_prefers_current_window() -> None:
    now = datetime(2026, 8, 27, 0, 20, 0, tzinfo=timezone.utc)
    markets = [
        {
            "ticker": "FUTURE",
            "status": "initialized",
            "open_time": "2026-08-27T00:30:00Z",
            "close_time": "2026-08-27T00:45:00Z",
        },
        {
            "ticker": "LIVE",
            "status": "active",
            "open_time": "2026-08-27T00:15:00Z",
            "close_time": "2026-08-27T00:30:00Z",
        },
        {
            "ticker": "DONE",
            "status": "active",
            "open_time": "2026-08-27T00:00:00Z",
            "close_time": "2026-08-27T00:15:00Z",
        },
    ]
    picked = pick_live_market(markets, now=now)
    assert picked is not None
    assert picked["ticker"] == "LIVE"


def test_gate_allows_live_current_window() -> None:
    now = datetime(2026, 8, 26, 3, 20, 0, tzinfo=timezone.utc)
    gate = evaluate_trading_gate(
        {
            "status": "active",
            "open_time": "2026-08-26T03:15:00Z",
            "close_time": "2026-08-26T03:30:00Z",
        },
        now=now,
    )
    assert gate.ok is True
    assert gate.reason == "ok"


def test_gate_blocks_when_not_accepting() -> None:
    now = datetime(2026, 8, 26, 3, 20, 0, tzinfo=timezone.utc)
    gate = evaluate_trading_gate(
        {
            "status": "initialized",
            "open_time": "2026-08-26T03:30:00Z",
            "close_time": "2026-08-26T03:45:00Z",
        },
        now=now,
    )
    assert gate.ok is False
    assert gate.reason == "market_not_started"


def test_gate_blocks_after_window_end() -> None:
    now = datetime(2026, 8, 26, 3, 30, 1, tzinfo=timezone.utc)
    gate = evaluate_trading_gate(
        {
            "status": "active",
            "open_time": "2026-08-26T03:15:00Z",
            "close_time": "2026-08-26T03:30:00Z",
        },
        now=now,
    )
    assert gate.ok is False
    assert gate.reason == "window_ended"
