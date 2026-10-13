"""Kalshi public Trade API helpers (unauthenticated market data)."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlencode

from btcpoly.config import Settings
from btcpoly.ingestion.collectors.http import fetch_text

_TIMEOUT = 15


def api_get(settings: Settings, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    base = settings.kalshi.api_base.rstrip("/")
    query = f"?{urlencode(params)}" if params else ""
    url = f"{base}{path}{query}"
    text = fetch_text(url, timeout=_TIMEOUT, attempts=2)
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise RuntimeError(f"kalshi unexpected payload at {path}")
    return payload


def as_float(value: Any, default: float = 0.0) -> float:
    if value in (None, ""):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
