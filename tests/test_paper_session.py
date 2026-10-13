from __future__ import annotations

from btcpoly.config import PaperSettings, Settings
from btcpoly.paper.session import PaperSessionState, session_trade_block
from btcpoly.timeutil import utcnow


def _settings(**paper_overrides: object) -> Settings:
    paper = PaperSettings(**{**PaperSettings().__dict__, **paper_overrides})
    return Settings(paper=paper)


def test_session_blocks_current_window_slug() -> None:
    settings = _settings()
    session = PaperSessionState(started_at=utcnow(), skip_market_slug="KXBTC15M-A")
    reason = session_trade_block(
        settings,
        session=session,
        decision="BUY_UP",
        slug="KXBTC15M-A",
        features={"mention_count_900": 5, "sentiment_net_900": 0.5},
    )
    assert reason == "session_wait_next_window"


def test_sentiment_requires_mentions_and_bullish_for_up() -> None:
    settings = _settings(require_fresh_btc_sentiment=True, min_sentiment_net_900=0.08)
    session = PaperSessionState(started_at=utcnow(), skip_market_slug=None)
    assert (
        session_trade_block(
            settings,
            session=session,
            decision="BUY_UP",
            slug="KXBTC15M-B",
            features={"mention_count_900": 0, "sentiment_net_900": 0.9},
        )
        == "no_recent_btc_news"
    )
    assert (
        session_trade_block(
            settings,
            session=session,
            decision="BUY_UP",
            slug="KXBTC15M-B",
            features={"mention_count_900": 2, "sentiment_net_900": 0.02},
        )
        == "btc_sentiment_not_bullish"
    )
    assert (
        session_trade_block(
            settings,
            session=session,
            decision="BUY_UP",
            slug="KXBTC15M-B",
            features={"mention_count_900": 2, "sentiment_net_900": 0.15},
        )
        is None
    )


def test_sentiment_bearish_for_down() -> None:
    settings = _settings(require_fresh_btc_sentiment=True, min_sentiment_net_900= 0.08)
    session = PaperSessionState(started_at=utcnow(), skip_market_slug=None)
    assert (
        session_trade_block(
            settings,
            session=session,
            decision="BUY_DOWN",
            slug="KXBTC15M-B",
            features={"mention_count_900": 3, "sentiment_net_900": 0.1},
        )
        == "btc_sentiment_not_bearish"
    )
    assert (
        session_trade_block(
            settings,
            session=session,
            decision="BUY_DOWN",
            slug="KXBTC15M-B",
            features={"mention_count_900": 3, "sentiment_net_900": -0.12},
        )
        is None
    )
