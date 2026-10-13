from __future__ import annotations

from datetime import datetime, timedelta, timezone

from btcpoly.config import load_settings
from btcpoly.ingestion.btc_market.spot import SpotSnapshot
from btcpoly.ingestion.kalshi.markets import MarketOdds, ResolvedMarket, TokenBook
from btcpoly.paper.execute import execute_paper
from btcpoly.timeutil import utcnow


def _book(token_id: str, mid: float, spread: float = 0.02) -> TokenBook:
    bid = mid - spread / 2
    ask = mid + spread / 2
    return TokenBook(
        token_id=token_id,
        best_bid=bid,
        best_ask=ask,
        mid=mid,
        spread=spread,
        bids=[{"price": bid, "size": 10}],
        asks=[{"price": ask, "size": 10}],
    )


def _active_raw(now: datetime | None = None) -> dict:
    now = now or utcnow()
    return {
        "status": "active",
        "open_time": (now - timedelta(minutes=5)).isoformat().replace("+00:00", "Z"),
        "close_time": (now + timedelta(minutes=10)).isoformat().replace("+00:00", "Z"),
        "yes_ask_dollars": "0.51",
        "no_ask_dollars": "0.51",
        "yes_bid_dollars": "0.49",
        "no_bid_dollars": "0.49",
        "floor_strike": 80000.0,
    }


def test_execute_paper_scores_with_mocks(memory_db, monkeypatch) -> None:
    from btcpoly.db.session import init_db, reset_engine

    reset_engine()
    settings = load_settings(env={"BTC_POLY_DATABASE_URL": "sqlite:///:memory:"}, load_dotenv_file=False)
    init_db(settings, url="sqlite:///:memory:")

    monkeypatch.setattr(
        "btcpoly.paper.execute.fetch_btc_return",
        lambda settings, window_seconds=60: SpotSnapshot(
            price=80000.0,
            event_ts=datetime.now(tz=timezone.utc),
            source="binance",
            ret=0.01,
            window_seconds=window_seconds,
        ),
    )
    market = ResolvedMarket(
        market_id="KXBTC15M-TEST",
        slug="KXBTC15M-TEST",
        question="Bitcoin Up or Down",
        up_token_id="YES",
        down_token_id="NO",
        start_ts=None,
        end_ts=None,
        outcome_prices=(0.5, 0.5),
        raw=_active_raw(),
    )
    monkeypatch.setattr("btcpoly.paper.execute.resolve_active_market", lambda settings: market)
    monkeypatch.setattr(
        "btcpoly.paper.execute.fetch_market_odds",
        lambda settings, m: MarketOdds(
            market_id=m.market_id,
            slug=m.slug,
            up=_book("YES", 0.50),
            down=_book("NO", 0.50),
            p_up_mid=0.50,
            p_down_mid=0.50,
            up_ask=0.51,
            down_ask=0.51,
            spread_up=0.02,
            source="kalshi",
        ),
    )

    payload = execute_paper(settings)
    assert payload["mode"] == "paper"
    assert payload["decision"] in {"NO_TRADE", "BUY_UP", "BUY_DOWN"}
    assert payload["reason"] != "no_model_yet"
    assert payload["btc_price"] == 80000.0
    assert payload["slug"] == "KXBTC15M-TEST"
    assert "p_up_model" in payload
    assert "edge" in payload
    assert isinstance(payload["sources"], list)
