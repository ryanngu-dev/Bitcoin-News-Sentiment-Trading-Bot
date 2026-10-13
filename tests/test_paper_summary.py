from __future__ import annotations

from io import StringIO

from rich.console import Console

from btcpoly.paper.summary import print_paper_summary


def test_print_paper_summary_is_compact() -> None:
    buf = StringIO()
    console = Console(file=buf, force_terminal=True, width=100)
    print_paper_summary(
        console,
        {
            "decision": "BUY_DOWN",
            "reason": "model_below_market",
            "slug": "btc-updown-15m-123",
            "btc_price": 78868.0,
            "btc_ret": 0.0001,
            "p_up_market": 0.785,
            "p_up_model": 0.50,
            "edge": -0.28,
            "spread": 0.01,
            "entry_price": 0.22,
            "size": 113.6,
            "trade_id": 25,
            "live_trading_armed": False,
            "bankroll": {
                "starting_cash": 100.0,
                "settled_pnl": 0.0,
                "open_cost": 25.0,
                "cash": 975.0,
            },
            "features": {
                "mention_count_300": 2,
                "mention_count_900": 5,
                "attn_z_300": 0.1,
                "attn_z_900": 1.2,
            },
            "sources": [
                {"platform": "rss", "title": "Bitcoin slips"},
                {"platform": "rss", "title": "BTC ETF"},
                {"platform": "reddit", "title": "moon?"},
                {"platform": "rss", "title": "extra1"},
                {"platform": "rss", "title": "extra2"},
                {"platform": "rss", "title": "extra3"},
            ],
        },
    )
    text = buf.getvalue()
    assert "BUY_DOWN" in text
    assert "78.5%" in text
    assert "50.0%" in text
    assert "Attention context" in text
    assert "used by model" in text
    assert "Cash:" in text
    assert "+1 more" in text
    assert "google.com" not in text
    # Rich markup / ANSI should mark the DOWN decision in red styling path.
    assert "BUY_DOWN" in text


def test_signed_styles() -> None:
    from btcpoly.paper.summary import _signed_style

    assert "green" in _signed_style(0.1)
    assert "red" in _signed_style(-0.1)
    assert _signed_style(0.0) == "dim"
