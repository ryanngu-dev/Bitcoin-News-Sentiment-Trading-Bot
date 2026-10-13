from __future__ import annotations

from datetime import timedelta

from btcpoly.config import load_settings
from btcpoly.db.models import PaperTrade, PolymarketMarket
from btcpoly.db.session import init_db, reset_engine, session_scope
from btcpoly.paper.settle import compute_binary_pnl, paper_pnl_stats, parse_winner, settle_paper_trades
from btcpoly.timeutil import utcnow


def test_compute_binary_pnl_win_and_loss() -> None:
    exit_w, pnl_w = compute_binary_pnl(size=100.0, entry_price=0.40, won=True)
    assert exit_w == 1.0
    assert abs(pnl_w - 60.0) < 1e-9
    exit_l, pnl_l = compute_binary_pnl(size=100.0, entry_price=0.40, won=False)
    assert exit_l == 0.0
    assert abs(pnl_l - (-40.0)) < 1e-9


def test_parse_winner_yes_no() -> None:
    assert parse_winner({"result": "yes", "status": "finalized"}) == "UP"
    assert parse_winner({"result": "no", "status": "finalized"}) == "DOWN"


def test_parse_winner_unresolved() -> None:
    assert parse_winner({"result": "", "status": "active"}) is None


def test_settle_skips_open_window_and_settles_resolved(monkeypatch) -> None:
    reset_engine()
    settings = load_settings(env={"BTC_POLY_DATABASE_URL": "sqlite:///:memory:"}, load_dotenv_file=False)
    init_db(settings, url="sqlite:///:memory:")
    now = utcnow()
    past_start = now - timedelta(minutes=30)
    past_end = now - timedelta(minutes=15)
    future_end = now + timedelta(minutes=10)
    past_slug = "KXBTC15M-PAST"
    open_slug = "KXBTC15M-OPEN"

    with session_scope() as session:
        session.add(
            PolymarketMarket(
                market_id="m-closed",
                slug=past_slug,
                question="Bitcoin Up or Down",
                up_token_id="u",
                down_token_id="d",
                start_ts=past_start,
                end_ts=past_end,
                status="active",
                raw_json={},
            )
        )
        session.add(
            PolymarketMarket(
                market_id="m-open",
                slug=open_slug,
                question="Bitcoin Up or Down",
                up_token_id="u2",
                down_token_id="d2",
                start_ts=now - timedelta(minutes=5),
                end_ts=future_end,
                status="active",
                raw_json={},
            )
        )
        session.add(
            PaperTrade(
                event_ts=past_start,
                market_id="m-closed",
                side="DOWN",
                size=100.0,
                entry_price=0.25,
                decision="BUY_DOWN",
                reason="test",
            )
        )
        session.add(
            PaperTrade(
                event_ts=now,
                market_id="m-open",
                side="UP",
                size=50.0,
                entry_price=0.50,
                decision="BUY_UP",
                reason="test",
            )
        )

    def fake_fetch(settings, ticker):
        if ticker == past_slug:
            return {"ticker": past_slug, "status": "finalized", "result": "no", "close_time": past_end.isoformat()}
        return {
            "ticker": open_slug,
            "status": "active",
            "result": "",
            "close_time": future_end.isoformat(),
        }

    monkeypatch.setattr("btcpoly.paper.settle.fetch_market_by_ticker", fake_fetch)
    result = settle_paper_trades(settings)
    assert result["settled"] == 1
    assert result["wins"] == 1
    assert result["skipped_open"] == 1
    assert abs(result["pnl_total"] - 75.0) < 1e-9

    with session_scope() as session:
        closed = session.get(PaperTrade, result["trades"][0]["trade_id"])
        assert closed is not None
        assert closed.exit_price == 1.0
        assert abs((closed.pnl or 0) - 75.0) < 1e-9
        stats = paper_pnl_stats(session)
        assert stats["settled"] == 1
        assert stats["open"] == 1
        assert stats["wins"] == 1


def test_settle_nets_fees_slippage(monkeypatch) -> None:
    reset_engine()
    settings = load_settings(env={"BTC_POLY_DATABASE_URL": "sqlite:///:memory:"}, load_dotenv_file=False)
    init_db(settings, url="sqlite:///:memory:")
    now = utcnow()
    past_start = now - timedelta(minutes=30)
    past_end = now - timedelta(minutes=15)
    past_slug = "KXBTC15M-FEE"

    with session_scope() as session:
        session.add(
            PolymarketMarket(
                market_id="m-fee",
                slug=past_slug,
                question="Bitcoin Up or Down",
                up_token_id="u",
                down_token_id="d",
                start_ts=past_start,
                end_ts=past_end,
                status="active",
                raw_json={},
            )
        )
        session.add(
            PaperTrade(
                event_ts=past_start,
                market_id="m-fee",
                side="UP",
                size=100.0,
                entry_price=0.40,
                fees=1.5,
                slippage=2.5,
                decision="BUY_UP",
                reason="test",
            )
        )

    monkeypatch.setattr(
        "btcpoly.paper.settle.fetch_market_by_ticker",
        lambda settings, ticker: {
            "ticker": past_slug,
            "status": "finalized",
            "result": "yes",
            "close_time": past_end.isoformat(),
        },
    )
    result = settle_paper_trades(settings)
    assert result["settled"] == 1
    assert abs(result["pnl_total"] - 56.0) < 1e-9
    assert abs(result["trades"][0]["binary_pnl"] - 60.0) < 1e-9
    assert "bankroll" in result
