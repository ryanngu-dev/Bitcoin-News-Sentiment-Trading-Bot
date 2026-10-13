"""Live Polymarket execution stub. Disabled unless two env flags and config agree."""

from __future__ import annotations

from typing import Any

from btcpoly.config import LIVE_TRADING_CONFIRM_VALUE, Settings, load_settings


class LiveTradingDisabledError(RuntimeError):
    """Raised whenever live order placement is attempted without full opt-in."""


def assert_live_trading_allowed(settings: Settings | None = None) -> Settings:
    resolved = settings or load_settings()
    if not resolved.execution.enabled:
        raise LiveTradingDisabledError(
            "Live trading is disabled in config (execution.enabled=false)."
        )
    if not resolved.live_trading_armed:
        raise LiveTradingDisabledError(
            "Live trading is not armed. Set BTC_POLY_LIVE_TRADING=1 and "
            f"BTC_POLY_LIVE_TRADING_CONFIRM={LIVE_TRADING_CONFIRM_VALUE}."
        )
    return resolved


def place_order(*_args: Any, settings: Settings | None = None, **_kwargs: Any) -> None:
    """Phase 14 stub. Always validates the kill switch first."""
    assert_live_trading_allowed(settings)
    raise NotImplementedError("Live CLOB execution is not implemented (Phase 14).")
