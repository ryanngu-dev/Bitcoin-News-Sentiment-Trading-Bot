from __future__ import annotations

import pytest

from btcpoly.config import LIVE_TRADING_CONFIRM_VALUE, load_settings
from btcpoly.live.execution import LiveTradingDisabledError, assert_live_trading_allowed, place_order


def test_assert_live_trading_blocked_by_default(settings) -> None:
    with pytest.raises(LiveTradingDisabledError):
        assert_live_trading_allowed(settings)


def test_place_order_stub_blocked(settings) -> None:
    with pytest.raises(LiveTradingDisabledError):
        place_order(settings=settings)


def test_armed_settings_still_unimplemented(tmp_yaml_config) -> None:
    settings = load_settings(
        tmp_yaml_config,
        env={
            "BTC_POLY_LIVE_TRADING": "1",
            "BTC_POLY_LIVE_TRADING_CONFIRM": LIVE_TRADING_CONFIRM_VALUE,
        },
        load_dotenv_file=False,
    )
    assert settings.live_trading_armed is True
    assert_live_trading_allowed(settings)
    with pytest.raises(NotImplementedError, match="Phase 14"):
        place_order(settings=settings)
