from __future__ import annotations

from datetime import datetime, timezone

from btcpoly.config import load_settings
from btcpoly.ingestion.kalshi.mode import series_ticker_for_duration, with_market_duration
from btcpoly.ingestion.kalshi.trading_hours import evaluate_trading_gate
from btcpoly.attention.sentiment import consensus_from_texts, score_text
from btcpoly.paper.run_loop import (
    format_banner,
    format_market_tick,
    format_outcome_line,
    format_session_line,
    format_trade_line,
)


def test_kalshi_series_15m_only() -> None:
    assert series_ticker_for_duration(15) == "KXBTC15M"


def test_with_market_duration_sets_kalshi(default_config_path) -> None:
    base = load_settings(default_config_path, env={}, load_dotenv_file=False)
    s15 = with_market_duration(base, 15)
    assert s15.kalshi.market_duration_minutes == 15
    assert s15.kalshi.series_ticker == "KXBTC15M"


def test_kalshi_gate_active_window() -> None:
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


def test_kalshi_gate_blocks_closed() -> None:
    now = datetime(2026, 8, 26, 3, 20, 0, tzinfo=timezone.utc)
    gate = evaluate_trading_gate(
        {
            "status": "finalized",
            "open_time": "2026-08-26T03:00:00Z",
            "close_time": "2026-08-26T03:15:00Z",
            "result": "yes",
        },
        now=now,
    )
    assert gate.ok is False


def test_format_trade_banner_up() -> None:
    trade = format_trade_line(
        {
            "decision": "BUY_UP",
            "trade_id": 9,
            "entry_price": 0.5,
            "size": 10,
            "edge": 0.1,
            "p_up_model": 0.62,
            "p_up_market": 0.48,
            "btc_ret": 0.0012,
            "slug": "KXBTC15M-TEST",
            "bankroll": {"cash": 90},
            "features": {"attn_z_900": 2.1, "sentiment_net_900": 0.4, "mention_count_900": 12},
            "sources": [
                {
                    "platform": "twitter",
                    "author": "whale_alert",
                    "title": "1000 BTC moved",
                    "url": "https://x.com/whale_alert/status/1",
                    "influence": True,
                }
            ],
            "why": {
                "summary": "Buying UP because the model is above Kalshi on P(UP): model P(UP)=62.0% vs Kalshi 48.0%",
                "links": [
                    {"label": "Kalshi market KXBTC15M-TEST", "url": "https://kalshi.com/markets/kxbtc15m"},
                    {
                        "label": "TWITTER @whale_alert — 1000 BTC moved",
                        "url": "https://x.com/whale_alert/status/1",
                    },
                ],
            },
        },
        session={
            "elapsed_seconds": 125,
            "trades_placed": 4,
            "wins": 3,
            "losses": 1,
        },
    )
    plain = trade.plain
    assert "=" * 40 in plain
    assert "PAPER TRADE PLACED — BUY UP" in plain
    assert "ABOVE the Kalshi strike" in plain
    assert "Amount bet: $5.00" in plain
    assert "Why:" in plain
    assert "https://x.com/whale_alert/status/1" in plain
    assert "Session: elapsed=2m 05s  trades=4  win rate=75% (3W/1L)" in plain
    assert plain.startswith("\n\n")


def test_build_trade_rationale_includes_links() -> None:
    from btcpoly.paper.rationale import build_trade_rationale, clickable_url

    why = build_trade_rationale(
        {
            "decision": "BUY_DOWN",
            "edge": -0.08,
            "p_up_model": 0.40,
            "p_up_market": 0.55,
            "btc_ret": -0.002,
            "slug": "KXBTC15M-26AUG262030-30",
            "features": {"attn_z_900": -0.2, "sentiment_net_900": -0.3},
            "sources": [
                {
                    "platform": "rss",
                    "title": "Bitcoin dips",
                    "url": "https://example.com/btc",
                    "influence": False,
                },
                {
                    "platform": "rss",
                    "title": "Broken google article",
                    "url": "https://news.google.com/rss/articles/CBMiabc123",
                    "influence": False,
                },
            ],
        }
    )
    assert "Buying DOWN" in why["lead"]
    assert why["bullets"]
    assert any("kalshi.com" in (x.get("url") or "") for x in why["links"])
    assert any("example.com/btc" in (x.get("url") or "") for x in why["links"])
    g = clickable_url(
        "https://news.google.com/rss/articles/CBMiabc123",
        title="Broken google article",
    )
    assert g is not None and "news.google.com/search" in g
    assert "kxbtc15m-26aug262030" in why["links"][0]["url"]
    assert not why["links"][0]["url"].endswith("-30")


def test_format_outcome_banner_win() -> None:
    win = format_outcome_line(
        {"won": True, "pnl": 12.5, "trade_id": 9, "side": "UP", "size": 10, "entry_price": 0.4}
    )
    lose = format_outcome_line(
        {"won": False, "pnl": -8.0, "trade_id": 8, "side": "DOWN", "size": 10, "entry_price": 0.5}
    )
    assert "YOU WON THIS TRADE" in win.plain
    assert "Original bet: $4.00" in win.plain
    assert "YOU LOST THIS TRADE" in lose.plain
    assert "DOWN (below strike) was wrong" in lose.plain
    assert any("green" in (span.style or "") for span in win.spans)
    assert any("red" in (span.style or "") for span in lose.spans)


def test_format_banner_shape() -> None:
    banner = format_banner(["HELLO"], style="bold red")
    assert banner.plain.startswith("\n\n")
    assert "=" * 40 in banner.plain
    assert "HELLO" in banner.plain


def test_format_market_tick_colors() -> None:
    up = format_market_tick(
        {"lean": "UP", "p_up": 0.62, "p_down": 0.38, "seconds_left": 120, "slug": "KXBTC15M-1", "book_open": True}
    )
    assert "UP" in up.plain and "BOOK OPEN" in up.plain


def test_format_session_line_win_rate() -> None:
    empty = format_session_line(
        elapsed_seconds=45, trades_placed=0, wins=0, losses=0
    )
    assert "elapsed=45s" in empty.plain
    assert "trades=0" in empty.plain
    assert "no settled trades yet" in empty.plain

    filled = format_session_line(
        elapsed_seconds=125, trades_placed=4, wins=3, losses=1
    )
    assert "elapsed=2m 05s" in filled.plain
    assert "trades=4" in filled.plain
    assert "win rate=75% (3W/1L)" in filled.plain


def test_sentiment_lexicon_consensus() -> None:
    assert score_text("BTC pumps hard, bullish breakout") == 1
    assert score_text("Bitcoin crash dump liquidations") == -1
    assert score_text("BTC price update") == 0
    c = consensus_from_texts(
        [
            "BTC rally surge",
            "bitcoin dump crash",
            "BTC moon pump",
            "just a chart",
        ]
    )
    assert c.scored == 4
    assert c.bullish == 2
    assert c.bearish == 1
    assert abs(c.net - 0.25) < 1e-9

def test_rss_prefers_body_and_sets_weight() -> None:
    from btcpoly.ingestion.agent_reach.normalizers import normalize_rss_entry
    from btcpoly.attention.credibility import is_trusted_source, source_weight

    assert source_weight(feed_url="https://www.coindesk.com/arc/outboundfeeds/rss/") > source_weight(
        feed_url="https://cryptopotato.com/feed/"
    )
    assert is_trusted_source(feed_url="https://www.coindesk.com/arc/outboundfeeds/rss/")
    assert not is_trusted_source(feed_url="https://cryptopotato.com/feed/")
    assert not is_trusted_source(feed_url="https://cointelegraph.com/rss")
    post = normalize_rss_entry(
        {
            "id": "abc",
            "title": "Bitcoin pumps hard",
            "summary": "<p>Traders say the rally may continue as ETF inflows surge.</p>",
            "link": "https://www.coindesk.com/markets/2026/08/26/bitcoin-pumps",
            "published": "Wed, 26 Aug 2026 20:00:00 +0000",
        },
        "https://www.coindesk.com/arc/outboundfeeds/rss/",
    )
    assert post is not None
    assert "ETF inflows" in (post.text or "")
    assert post.raw_json.get("source_weight", 0) >= 1.2


def test_weighted_sentiment_prefers_credible() -> None:
    from btcpoly.attention.sentiment import consensus_from_weighted

    # One high-weight bullish vs many low-weight bearish should still lean bullish.
    c = consensus_from_weighted(
        [
            ("Bitcoin ETF approval rally surge", 1.45),
            ("bitcoin dump crash", 0.7),
            ("btc dump", 0.7),
        ]
    )
    assert c.net > 0
