from __future__ import annotations

from btcpoly.config import LIVE_TRADING_CONFIRM_VALUE, apply_env_overlay, load_settings


def test_default_live_trading_is_off(default_config_path) -> None:
    settings = load_settings(
        default_config_path,
        env={},
        load_dotenv_file=False,
    )
    assert settings.execution.enabled is False
    assert settings.live_trading_armed is False
    assert settings.kalshi.market_duration_minutes == 15
    assert settings.kalshi.series_ticker == "KXBTC15M"
    assert settings.ingest.interval_seconds == 0
    assert settings.risk.min_edge == 0.04
    assert settings.btc_market.spot_source == "binance"


def test_env_overlay_database_and_duration(tmp_yaml_config) -> None:
    env = {
        "BTC_POLY_DATABASE_URL": "sqlite:////tmp/research.db",
        "BTC_POLY_MARKET_DURATION_MINUTES": "15",
        "BTC_POLY_LOG_LEVEL": "debug",
        "BTC_POLY_LIVE_TRADING": "0",
    }
    settings = load_settings(tmp_yaml_config, env=env, load_dotenv_file=False)
    assert settings.database.url == "sqlite:////tmp/research.db"
    assert settings.kalshi.market_duration_minutes == 15
    assert settings.logging.level == "DEBUG"
    assert settings.execution.enabled is False


def test_live_trading_env_alone_does_not_arm(tmp_yaml_config) -> None:
    settings = load_settings(
        tmp_yaml_config,
        env={"BTC_POLY_LIVE_TRADING": "1"},
        load_dotenv_file=False,
    )
    assert settings.execution.enabled is True
    assert settings.live_trading_armed is False


def test_live_trading_armed_only_with_confirm(tmp_yaml_config) -> None:
    settings = load_settings(
        tmp_yaml_config,
        env={
            "BTC_POLY_LIVE_TRADING": "1",
            "BTC_POLY_LIVE_TRADING_CONFIRM": LIVE_TRADING_CONFIRM_VALUE,
        },
        load_dotenv_file=False,
    )
    assert settings.live_trading_armed is True


def test_apply_env_overlay_ignores_missing_keys() -> None:
    data = {"execution": {"enabled": False}, "database": {"url": "sqlite:///a.db"}}
    out = apply_env_overlay(data, {})
    assert out["execution"]["enabled"] is False
    assert out["database"]["url"] == "sqlite:///a.db"
