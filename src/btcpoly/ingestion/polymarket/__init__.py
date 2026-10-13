"""Polymarket Gamma / CLOB collectors."""

from btcpoly.ingestion.polymarket.clob import MarketOdds, fetch_market_odds
from btcpoly.ingestion.polymarket.gamma import (
    ResolvedMarket,
    fetch_market_by_slug,
    resolve_active_market,
)
from btcpoly.ingestion.polymarket.slug import candidate_slugs, market_slug

__all__ = [
    "MarketOdds",
    "ResolvedMarket",
    "candidate_slugs",
    "fetch_market_by_slug",
    "fetch_market_odds",
    "market_slug",
    "resolve_active_market",
]
