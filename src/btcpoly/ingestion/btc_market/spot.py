"""Binance BTC spot + short-horizon return helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode

from btcpoly.config import Settings
from btcpoly.db.models import BtcTick
from btcpoly.db.session import session_scope
from btcpoly.ingestion.collectors.http import fetch_text
from btcpoly.timeutil import utcnow

_DEFAULT_TIMEOUT = 10

# api.binance.com is often geo-blocked (HTTP 451); vision/us mirrors usually work.
_BINANCE_REST_FALLBACKS = (
    "https://data-api.binance.vision",
    "https://api.binance.us",
    "https://api.binance.com",
)


@dataclass(frozen=True)
class SpotSnapshot:
    price: float
    event_ts: datetime
    source: str
    ret: float | None = None
    window_seconds: int | None = None
    extra: dict[str, Any] | None = None


def _rest_bases(settings: Settings) -> list[str]:
    primary = (settings.btc_market.binance_rest or "").rstrip("/")
    out: list[str] = []
    if primary:
        out.append(primary)
    for base in _BINANCE_REST_FALLBACKS:
        if base not in out:
            out.append(base)
    return out


def _get_json(url: str, *, timeout: int) -> Any:
    return json.loads(fetch_text(url, timeout=timeout, attempts=1))


def _fetch_binance_json(settings: Settings, path_and_query: str, *, timeout: int) -> tuple[Any, str]:
    errors: list[str] = []
    for base in _rest_bases(settings):
        url = f"{base}{path_and_query}"
        try:
            return _get_json(url, timeout=timeout), base
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{base}: {exc}")
    raise RuntimeError("all BTC spot endpoints failed: " + " | ".join(errors))


def _persist_tick(
    *,
    source: str,
    price: float,
    event_ts: datetime,
    volume: float | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    now = utcnow()
    with session_scope() as session:
        session.add(
            BtcTick(
                source=source,
                event_ts=event_ts,
                ingested_at=now,
                price=price,
                volume=volume,
                extra=extra or {},
            )
        )


def fetch_btc_spot(settings: Settings, *, timeout: int = _DEFAULT_TIMEOUT) -> SpotSnapshot:
    payload, base = _fetch_binance_json(
        settings, "/api/v3/ticker/price?symbol=BTCUSDT", timeout=timeout
    )
    price = float(payload["price"])
    now = utcnow()
    source = settings.btc_market.spot_source or "binance"
    _persist_tick(
        source=source,
        price=price,
        event_ts=now,
        extra={"symbol": "BTCUSDT", "rest": base, "raw": payload},
    )
    return SpotSnapshot(
        price=price,
        event_ts=now,
        source=source,
        extra={"symbol": "BTCUSDT", "rest": base},
    )


def fetch_btc_return(
    settings: Settings,
    *,
    window_seconds: int = 60,
    timeout: int = _DEFAULT_TIMEOUT,
) -> SpotSnapshot:
    """Spot price plus simple return over ~window_seconds using 1m klines."""
    limit = max(2, min(60, (window_seconds // 60) + 2))
    query = urlencode({"symbol": "BTCUSDT", "interval": "1m", "limit": str(limit)})
    try:
        rows, base = _fetch_binance_json(settings, f"/api/v3/klines?{query}", timeout=timeout)
    except RuntimeError:
        spot = fetch_btc_spot(settings, timeout=timeout)
        return SpotSnapshot(
            price=spot.price,
            event_ts=spot.event_ts,
            source=spot.source,
            ret=0.0,
            window_seconds=window_seconds,
            extra={"klines": "unavailable", **(spot.extra or {})},
        )

    if not isinstance(rows, list) or len(rows) < 2:
        spot = fetch_btc_spot(settings, timeout=timeout)
        return SpotSnapshot(
            price=spot.price,
            event_ts=spot.event_ts,
            source=spot.source,
            ret=0.0,
            window_seconds=window_seconds,
            extra={"klines": "insufficient", "rest": base},
        )

    closes = [float(row[4]) for row in rows]
    price = closes[-1]
    bars = max(1, window_seconds // 60)
    start_idx = max(0, len(closes) - 1 - bars)
    start = closes[start_idx]
    ret = 0.0 if start <= 0 else (price - start) / start
    open_ms = int(rows[-1][0])
    event_ts = datetime.fromtimestamp(open_ms / 1000.0, tz=timezone.utc)
    source = settings.btc_market.spot_source or "binance"
    _persist_tick(
        source=source,
        price=price,
        event_ts=event_ts,
        volume=float(rows[-1][5]) if rows[-1][5] not in (None, "") else None,
        extra={
            "symbol": "BTCUSDT",
            "ret": ret,
            "window_seconds": window_seconds,
            "rest": base,
        },
    )
    return SpotSnapshot(
        price=price,
        event_ts=event_ts,
        source=source,
        ret=ret,
        window_seconds=window_seconds,
        extra={"bars": bars, "start_price": start, "rest": base},
    )
