from __future__ import annotations

from datetime import datetime, timezone

from btcpoly.ingestion.polymarket.slug import candidate_slugs, market_slug, window_start_unix
from btcpoly.models.baseline import score_momentum


def test_window_start_floors_to_duration() -> None:
    now = datetime(2026, 8, 25, 20, 7, 30, tzinfo=timezone.utc)
    assert window_start_unix(now, duration_minutes=15) == int(datetime(2026, 8, 25, 20, 0, tzinfo=timezone.utc).timestamp())


def test_market_slug_uses_prefix_and_window() -> None:
    now = datetime(2026, 8, 25, 20, 7, 30, tzinfo=timezone.utc)
    slug = market_slug("btc-updown-15m", duration_minutes=15, now=now)
    assert slug.startswith("btc-updown-15m-")
    assert slug.endswith(str(window_start_unix(now, duration_minutes=15)))


def test_candidate_slugs_include_neighbors() -> None:
    now = datetime(2026, 8, 25, 20, 7, 30, tzinfo=timezone.utc)
    slugs = candidate_slugs("btc-updown-15m", duration_minutes=15, now=now)
    assert len(slugs) == 3
    assert len(set(slugs)) == 3


def test_score_momentum_no_trade_when_edge_small() -> None:
    score = score_momentum(
        ret=0.0001,
        p_up_market=0.50,
        up_ask=0.51,
        down_ask=0.51,
        spread=0.01,
        min_edge=0.08,
        max_spread=0.04,
        max_position_usd=25.0,
    )
    assert score.decision == "NO_TRADE"
    assert score.reason == "edge_below_min"


def test_score_momentum_buy_up_on_strong_positive_ret() -> None:
    score = score_momentum(
        ret=0.01,
        p_up_market=0.50,
        up_ask=0.52,
        down_ask=0.50,
        spread=0.01,
        min_edge=0.08,
        max_spread=0.04,
        max_position_usd=25.0,
    )
    assert score.decision == "BUY_UP"
    assert score.side == "UP"
    assert score.entry_price == 0.52
    assert score.size > 0
    assert score.edge >= 0.08


def test_score_momentum_rejects_wide_spread() -> None:
    score = score_momentum(
        ret=0.01,
        p_up_market=0.50,
        up_ask=0.60,
        down_ask=0.40,
        spread=0.20,
        min_edge=0.08,
        max_spread=0.04,
        max_position_usd=25.0,
    )
    assert score.decision == "NO_TRADE"
    assert score.reason == "spread_too_wide"


def test_score_momentum_rejects_low_confidence() -> None:
    score = score_momentum(
        ret=0.01,
        p_up_market=0.50,
        up_ask=0.52,
        down_ask=0.50,
        spread=0.01,
        min_edge=0.08,
        max_spread=0.04,
        max_position_usd=25.0,
        min_confidence=0.9,
    )
    assert score.decision == "NO_TRADE"
    assert score.reason == "confidence_below_min"
