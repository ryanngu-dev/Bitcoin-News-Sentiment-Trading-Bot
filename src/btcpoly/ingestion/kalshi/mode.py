"""Kalshi BTC up/down series mode (15m)."""

from __future__ import annotations

from dataclasses import replace

from btcpoly.config import Settings

# Kalshi has no 5m BTC up/down series; official short window is 15m.
SUPPORTED_DURATIONS: tuple[int, ...] = (15,)
SERIES_BY_DURATION: dict[int, str] = {
    15: "KXBTC15M",
}


def series_ticker_for_duration(minutes: int, settings: Settings | None = None) -> str:
    minutes = int(minutes)
    if settings is not None and minutes == int(settings.kalshi.market_duration_minutes):
        return settings.kalshi.series_ticker
    if minutes not in SERIES_BY_DURATION:
        raise ValueError(
            f"Kalshi BTC up/down supports only {SUPPORTED_DURATIONS} minute markets "
            f"(no 5m). Got {minutes}."
        )
    return SERIES_BY_DURATION[minutes]


def with_market_duration(settings: Settings, minutes: int) -> Settings:
    minutes = int(minutes)
    series = series_ticker_for_duration(minutes)
    return replace(
        settings,
        kalshi=replace(
            settings.kalshi,
            market_duration_minutes=minutes,
            series_ticker=series,
        ),
    )
