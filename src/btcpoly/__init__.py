"""Research-first BTC attention system for Polymarket. Live trading off by default."""

__version__ = "0.1.0"

from btcpoly.live.execution import LiveTradingDisabledError, assert_live_trading_allowed

__all__ = [
    "__version__",
    "LiveTradingDisabledError",
    "assert_live_trading_allowed",
]
