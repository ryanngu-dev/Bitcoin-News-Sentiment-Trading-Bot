"""Kalshi BTC up/down market data (official USA-accessible exchange)."""

from btcpoly.ingestion.kalshi.markets import (
    MarketOdds,
    ResolvedMarket,
    expand_ticker_candidates,
    fetch_market_by_ticker,
    fetch_market_odds,
    parse_winner,
    resolve_active_market,
)
from btcpoly.ingestion.kalshi.mode import with_market_duration
from btcpoly.ingestion.kalshi.trading_hours import evaluate_trading_gate

__all__ = [
    "MarketOdds",
    "ResolvedMarket",
    "evaluate_trading_gate",
    "expand_ticker_candidates",
    "fetch_market_by_ticker",
    "fetch_market_odds",
    "parse_winner",
    "resolve_active_market",
    "with_market_duration",
]
