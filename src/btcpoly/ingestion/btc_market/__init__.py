"""BTC market package."""

from btcpoly.ingestion.btc_market.spot import SpotSnapshot, fetch_btc_return, fetch_btc_spot

__all__ = ["SpotSnapshot", "fetch_btc_return", "fetch_btc_spot"]
