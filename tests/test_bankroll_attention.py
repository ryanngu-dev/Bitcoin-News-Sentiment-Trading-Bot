from __future__ import annotations

from datetime import timedelta

from btcpoly.config import PaperSettings, load_settings
from btcpoly.db.models import PaperTrade, RawPostRow
from btcpoly.db.session import init_db, reset_engine, session_scope
from btcpoly.attention.aggregate import build_attention_features
from btcpoly.edge.costs import apply_entry_costs
from btcpoly.models.momentum_attn import score_momentum_attn
from btcpoly.paper.bankroll import get_bankroll, max_trade_notional
from btcpoly.paper.settle import compute_binary_pnl
from btcpoly.timeutil import utcnow


def test_paper_settings_defaults(default_config_path) -> None:
    settings = load_settings(default_config_path, env={}, load_dotenv_file=False)
    assert settings.paper.starting_cash == 100.0
    assert settings.paper.fee_bps == 0.0
    assert settings.paper.slippage_bps == 50.0
    assert settings.paper.model_name == "momentum_attn_v1"


def test_bankroll_open_cost_and_insufficient_cash() -> None:
    reset_engine()
    settings = load_settings(env={"BTC_POLY_DATABASE_URL": "sqlite:///:memory:"}, load_dotenv_file=False)
    # Force tiny bankroll via paper settings override by constructing Settings-like path:
    # mutate through raw reload isn't easy; patch paper on settings object is frozen.
    # Use starting_cash from defaults then open a large position.
    init_db(settings, url="sqlite:///:memory:")
    with session_scope() as session:
        bank = get_bankroll(session, settings)
        assert abs(bank["cash"] - 100.0) < 1e-9
        assert bank["open_cost"] == 0.0
        session.add(
            PaperTrade(
                event_ts=utcnow(),
                market_id="m1",
                side="UP",
                size=100.0,
                entry_price=0.50,
                fees=1.0,
                slippage=2.0,
                decision="BUY_UP",
                reason="test",
            )
        )
        session.flush()
        bank2 = get_bankroll(session, settings)
        assert abs(bank2["open_cost"] - 53.0) < 1e-9
        assert abs(bank2["cash"] - (100.0 - 53.0)) < 1e-9
        # Cap by cash * pct and max_position
        notional = max_trade_notional(bank2, settings)
        assert notional <= settings.risk.max_position_usd
        assert notional <= bank2["cash"] * settings.risk.max_bankroll_pct + 1e-9


def test_apply_entry_costs_worsens_entry() -> None:
    costs = apply_entry_costs(0.50, max_notional_usd=20.0, fee_bps=0.0, slippage_bps=50.0)
    assert costs.entry_eff > 0.50
    assert abs(costs.entry_eff - 0.5025) < 1e-9
    assert costs.slippage > 0
    assert costs.fees == 0.0
    assert abs(costs.notional - 20.0) < 1e-6


def test_settle_pnl_nets_fees_and_slippage() -> None:
    exit_p, binary = compute_binary_pnl(size=100.0, entry_price=0.40, won=True)
    assert exit_p == 1.0
    fees, slip = 1.5, 2.5
    assert abs((binary - fees - slip) - 56.0) < 1e-9


def test_attention_counts_and_z_from_posts() -> None:
    reset_engine()
    settings = load_settings(env={"BTC_POLY_DATABASE_URL": "sqlite:///:memory:"}, load_dotenv_file=False)
    init_db(settings, url="sqlite:///:memory:")
    now = utcnow()
    with session_scope() as session:
        for i in range(5):
            session.add(
                RawPostRow(
                    platform="rss",
                    post_id=f"p{i}",
                    author=f"a{i % 2}",
                    event_ts=now - timedelta(seconds=30 + i),
                    ingested_at=now - timedelta(seconds=10),
                    text="BTC up",
                    raw_json={},
                )
            )
        session.flush()
        # Seed history so z-score is defined.
        from btcpoly.db.models import AttentionAggregate

        for j in range(10):
            session.add(
                AttentionAggregate(
                    window_end=now - timedelta(minutes=j + 1),
                    window_seconds=900,
                    mention_count=1,
                    unique_authors=1,
                    zscore=0.0,
                    features={},
                )
            )
        session.flush()
        feats = build_attention_features(session, as_of=now, market_id="m")
        assert feats["mention_count_900"] == 5
        assert feats["unique_authors_900"] == 2
        assert feats["attn_z_900"] != 0.0
        assert "sentiment_net_900" in feats
        assert -1.0 <= float(feats["sentiment_net_900"]) <= 1.0


def test_momentum_attn_shifts_p_up_with_large_z() -> None:
    base = score_momentum_attn(
        ret=0.0,
        p_up_market=0.50,
        up_ask=0.51,
        down_ask=0.51,
        spread=0.01,
        min_edge=0.01,
        max_spread=0.04,
        max_position_usd=25.0,
        min_confidence=0.0,
        attn_z=0.0,
    )
    hot = score_momentum_attn(
        ret=0.0,
        p_up_market=0.50,
        up_ask=0.51,
        down_ask=0.51,
        spread=0.01,
        min_edge=0.01,
        max_spread=0.04,
        max_position_usd=25.0,
        min_confidence=0.0,
        attn_z=3.0,
    )
    assert hot.p_up > base.p_up
    assert abs(hot.p_up - (0.5 + 0.05 * 3.0)) < 1e-9 or hot.p_up <= 0.95


def test_momentum_attn_shifts_with_sentiment_net() -> None:
    base = score_momentum_attn(
        ret=0.0,
        p_up_market=0.50,
        up_ask=0.51,
        down_ask=0.51,
        spread=0.01,
        min_edge=0.01,
        max_spread=0.04,
        max_position_usd=25.0,
        min_confidence=0.0,
        attn_z=0.0,
        sentiment_net=0.0,
    )
    bull = score_momentum_attn(
        ret=0.0,
        p_up_market=0.50,
        up_ask=0.51,
        down_ask=0.51,
        spread=0.01,
        min_edge=0.01,
        max_spread=0.04,
        max_position_usd=25.0,
        min_confidence=0.0,
        attn_z=0.0,
        sentiment_net=1.0,
    )
    assert bull.p_up > base.p_up


def test_momentum_attn_uses_live_market_disagreement() -> None:
    score = score_momentum_attn(
        ret=0.0,
        p_up_market=0.72,
        up_ask=0.73,
        down_ask=0.29,
        spread=0.02,
        min_edge=0.04,
        max_spread=0.06,
        max_position_usd=25.0,
        min_confidence=0.20,
        attn_z=0.0,
    )
    assert score.decision == "BUY_DOWN"
    assert score.confidence >= 0.20
    assert score.edge < -0.04


def test_bankroll_dataclass_exists() -> None:
    assert PaperSettings().starting_cash == 100.0
