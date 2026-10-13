from __future__ import annotations

import copy
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import yaml
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "default.yaml"
LIVE_TRADING_CONFIRM_VALUE = "I_UNDERSTAND"


def _deep_merge(base: dict[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in override.items():
        if (
            key in merged
            and isinstance(merged[key], dict)
            and isinstance(value, Mapping)
        ):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _as_int(value: Any, default: int) -> int:
    if value is None or value == "":
        return default
    return int(value)


def _as_float(value: Any, default: float) -> float:
    if value is None or value == "":
        return default
    return float(value)


@dataclass(frozen=True)
class ExecutionSettings:
    enabled: bool = False
    require_confirm_env: bool = True


@dataclass(frozen=True)
class DatabaseSettings:
    url: str = "sqlite:///data/btcpoly.db"
    echo: bool = False


@dataclass(frozen=True)
class LoggingSettings:
    level: str = "INFO"
    json: bool = False


@dataclass(frozen=True)
class KalshiSettings:
    """Official exchange for paper BTC up/down (USA-accessible)."""

    api_base: str = "https://api.elections.kalshi.com/trade-api/v2"
    series_ticker: str = "KXBTC15M"
    market_duration_minutes: int = 15
    order_min_size: float = 1.0
    # Optional Kalshi URL or ticker hint when series listing misses the live window.
    market_ticker: str = ""
    # Kept for UI links / status labels.
    exchange_name: str = "kalshi"


@dataclass(frozen=True)
class AgentReachSettings:
    doctor_timeout_seconds: int = 45
    doctor_command: tuple[str, ...] = ("agent-reach", "doctor", "--json")
    channels: tuple[str, ...] = ()


@dataclass(frozen=True)
class IngestSettings:
    limit: int = 15
    timeout_seconds: int = 60
    interval_seconds: int = 0
    # Only keep mentions newer than this (trading-relevant freshness).
    max_age_minutes: int = 45
    rss_feeds: tuple[str, ...] = ()
    news_urls: tuple[str, ...] = ()


@dataclass(frozen=True)
class BtcMarketSettings:
    windows_seconds: tuple[int, ...] = (10, 30, 60, 300, 900, 3600)
    spot_source: str = "binance"
    resolution_source: str = "kalshi"
    binance_rest: str = "https://api.binance.com"


@dataclass(frozen=True)
class RiskSettings:
    max_position_usd: float = 25.0
    max_bankroll_pct: float = 0.25
    max_daily_loss_usd: float = 50.0
    max_simultaneous_positions: int = 1
    min_edge: float = 0.04
    min_confidence: float = 0.20
    max_spread: float = 0.06
    cooldown_seconds: int = 60
    emergency_stop: bool = False


@dataclass(frozen=True)
class PaperSettings:
    starting_cash: float = 100.0
    fee_bps: float = 0.0
    slippage_bps: float = 50.0
    model_name: str = "momentum_attn_v1"
    # ``btcpoly run`` session behavior (one-shot ``execute`` ignores these).
    reset_on_run: bool = True
    wait_next_window_on_run: bool = True
    require_fresh_btc_sentiment: bool = True
    min_mention_count_900: int = 1
    min_sentiment_net_900: float = 0.08


@dataclass(frozen=True)
class AiSentimentSettings:
    """Optional LLM lean scores for recent headlines (hybrid with lexicon)."""

    enabled: bool = True
    provider: str = "auto"  # auto | groq | openai
    model: str = ""
    max_posts: int = 15
    timeout_seconds: int = 20
    lookback_seconds: int = 900


@dataclass(frozen=True)
class Settings:
    hypothesis: str = ""
    logging: LoggingSettings = field(default_factory=LoggingSettings)
    database: DatabaseSettings = field(default_factory=DatabaseSettings)
    execution: ExecutionSettings = field(default_factory=ExecutionSettings)
    kalshi: KalshiSettings = field(default_factory=KalshiSettings)
    btc_market: BtcMarketSettings = field(default_factory=BtcMarketSettings)
    risk: RiskSettings = field(default_factory=RiskSettings)
    paper: PaperSettings = field(default_factory=PaperSettings)
    ai_sentiment: AiSentimentSettings = field(default_factory=AiSentimentSettings)
    agent_reach: AgentReachSettings = field(default_factory=AgentReachSettings)
    ingest: IngestSettings = field(default_factory=IngestSettings)
    attention_windows_seconds: tuple[int, ...] = (60, 300, 900, 3600)
    btc_windows_seconds: tuple[int, ...] = (10, 30, 60, 300, 900, 3600)
    attention_queries: tuple[str, ...] = ("BTC", "Bitcoin", "$BTC")
    kol_twitter: tuple[str, ...] = ()
    live_trading_env: bool = False
    live_trading_confirm: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def live_trading_armed(self) -> bool:
        """True only if config, LIVE_TRADING env, and confirm env all allow it."""
        if not self.execution.enabled:
            return False
        if not self.live_trading_env:
            return False
        if self.execution.require_confirm_env:
            return self.live_trading_confirm == LIVE_TRADING_CONFIRM_VALUE
        return True


def apply_env_overlay(data: dict[str, Any], env: Mapping[str, str]) -> dict[str, Any]:
    """Overlay well-known BTC_POLY_* environment variables onto loaded YAML."""
    out = copy.deepcopy(data)
    out.setdefault("execution", {})
    out.setdefault("database", {})
    out.setdefault("logging", {})
    out.setdefault("kalshi", {})

    if "BTC_POLY_LIVE_TRADING" in env:
        out["execution"]["enabled"] = _as_bool(env.get("BTC_POLY_LIVE_TRADING"))
    if env.get("BTC_POLY_DATABASE_URL"):
        out["database"]["url"] = env["BTC_POLY_DATABASE_URL"]
    if env.get("BTC_POLY_LOG_LEVEL"):
        out["logging"]["level"] = env["BTC_POLY_LOG_LEVEL"].upper()
    duration = env.get("BTC_POLY_MARKET_DURATION_MINUTES")
    if duration:
        out.setdefault("kalshi", {})
        out["kalshi"]["market_duration_minutes"] = int(duration)
    if "BTC_POLY_AI_SENTIMENT" in env:
        out.setdefault("ai_sentiment", {})
        out["ai_sentiment"]["enabled"] = _as_bool(env.get("BTC_POLY_AI_SENTIMENT"), default=True)
    return out


def _settings_from_dict(data: dict[str, Any], env: Mapping[str, str]) -> Settings:
    exec_raw = data.get("execution") or {}
    db_raw = data.get("database") or {}
    log_raw = data.get("logging") or {}
    poly_raw = data.get("kalshi") or data.get("polymarket") or {}
    reach_raw = data.get("agent_reach") or {}
    attention = data.get("attention") or {}
    btc = data.get("btc_market") or {}
    risk_raw = data.get("risk") or {}
    paper_raw = data.get("paper") or {}
    ai_raw = data.get("ai_sentiment") or {}
    kol = data.get("kol_watchlist") or {}
    ingest_raw = data.get("ingest") or {}
    cmd = reach_raw.get("doctor_command") or ["agent-reach", "doctor", "--json"]
    btc_windows = tuple(int(x) for x in (btc.get("windows_seconds") or (10, 30, 60, 300, 900, 3600)))
    return Settings(
        hypothesis=str(data.get("hypothesis") or "").strip(),
        logging=LoggingSettings(
            level=str(log_raw.get("level") or "INFO").upper(),
            json=bool(log_raw.get("json", False)),
        ),
        database=DatabaseSettings(
            url=str(db_raw.get("url") or "sqlite:///data/btcpoly.db"),
            echo=bool(db_raw.get("echo", False)),
        ),
        execution=ExecutionSettings(
            enabled=bool(exec_raw.get("enabled", False)),
            require_confirm_env=bool(exec_raw.get("require_confirm_env", True)),
        ),
        kalshi=KalshiSettings(
            api_base=str(
                poly_raw.get("api_base")
                or "https://api.elections.kalshi.com/trade-api/v2"
            ),
            series_ticker=str(poly_raw.get("series_ticker") or "KXBTC15M"),
            market_duration_minutes=int(poly_raw.get("market_duration_minutes") or 15),
            order_min_size=_as_float(poly_raw.get("order_min_size"), 1.0),
            market_ticker=str(poly_raw.get("market_ticker") or ""),
            exchange_name=str(poly_raw.get("exchange_name") or "kalshi"),
        ),
        btc_market=BtcMarketSettings(
            windows_seconds=btc_windows,
            spot_source=str(btc.get("spot_source") or "binance"),
            resolution_source=str(btc.get("resolution_source") or "kalshi"),
            binance_rest=str(btc.get("binance_rest") or "https://api.binance.com"),
        ),
        risk=RiskSettings(
            max_position_usd=_as_float(risk_raw.get("max_position_usd"), 25.0),
            max_bankroll_pct=_as_float(risk_raw.get("max_bankroll_pct"), 0.25),
            max_daily_loss_usd=_as_float(risk_raw.get("max_daily_loss_usd"), 50.0),
            max_simultaneous_positions=_as_int(risk_raw.get("max_simultaneous_positions"), 1),
            min_edge=_as_float(risk_raw.get("min_edge"), 0.04),
            min_confidence=_as_float(risk_raw.get("min_confidence"), 0.20),
            max_spread=_as_float(risk_raw.get("max_spread"), 0.06),
            cooldown_seconds=_as_int(risk_raw.get("cooldown_seconds"), 60),
            emergency_stop=bool(risk_raw.get("emergency_stop", False)),
        ),
        paper=PaperSettings(
            starting_cash=_as_float(paper_raw.get("starting_cash"), 100.0),
            fee_bps=_as_float(paper_raw.get("fee_bps"), 0.0),
            slippage_bps=_as_float(paper_raw.get("slippage_bps"), 50.0),
            model_name=str(paper_raw.get("model_name") or "momentum_attn_v1"),
            reset_on_run=bool(paper_raw.get("reset_on_run", True)),
            wait_next_window_on_run=bool(paper_raw.get("wait_next_window_on_run", True)),
            require_fresh_btc_sentiment=bool(paper_raw.get("require_fresh_btc_sentiment", True)),
            min_mention_count_900=_as_int(paper_raw.get("min_mention_count_900"), 1),
            min_sentiment_net_900=_as_float(paper_raw.get("min_sentiment_net_900"), 0.08),
        ),
        ai_sentiment=AiSentimentSettings(
            enabled=bool(ai_raw.get("enabled", True)),
            provider=str(ai_raw.get("provider") or "auto"),
            model=str(ai_raw.get("model") or ""),
            max_posts=_as_int(ai_raw.get("max_posts"), 10),
            timeout_seconds=_as_int(ai_raw.get("timeout_seconds"), 20),
            lookback_seconds=_as_int(ai_raw.get("lookback_seconds"), 900),
        ),
        agent_reach=AgentReachSettings(
            doctor_timeout_seconds=int(reach_raw.get("doctor_timeout_seconds") or 45),
            doctor_command=tuple(str(x) for x in cmd),
            channels=tuple(str(x) for x in (reach_raw.get("channels") or ())),
        ),
        ingest=IngestSettings(
            limit=_as_int(ingest_raw.get("limit"), 15),
            timeout_seconds=_as_int(ingest_raw.get("timeout_seconds"), 60),
            interval_seconds=_as_int(ingest_raw.get("interval_seconds"), 0),
            max_age_minutes=(
                _as_int(ingest_raw.get("max_age_minutes"), 45)
                if ingest_raw.get("max_age_minutes") is not None
                else (
                    _as_int(ingest_raw.get("max_age_hours"), 1) * 60
                    if ingest_raw.get("max_age_hours") is not None
                    else 45
                )
            ),
            rss_feeds=tuple(str(x) for x in (ingest_raw.get("rss_feeds") or ())),
            news_urls=tuple(str(x) for x in (ingest_raw.get("news_urls") or ())),
        ),
        attention_windows_seconds=tuple(
            int(x) for x in (attention.get("windows_seconds") or (60, 300, 900, 3600))
        ),
        btc_windows_seconds=btc_windows,
        attention_queries=tuple(str(x) for x in (attention.get("queries") or ("BTC",))),
        kol_twitter=tuple(str(x) for x in (kol.get("twitter") or ())),
        live_trading_env=_as_bool(env.get("BTC_POLY_LIVE_TRADING"), default=False),
        live_trading_confirm=env.get("BTC_POLY_LIVE_TRADING_CONFIRM"),
        raw=data,
    )


def load_settings(
    config_path: str | Path | None = None,
    env: Mapping[str, str] | None = None,
    *,
    load_dotenv_file: bool = True,
) -> Settings:
    if load_dotenv_file:
        env_file = REPO_ROOT / ".env"
        if env_file.exists():
            load_dotenv(env_file, override=False)

    path = Path(
        config_path
        or (env or os.environ).get("BTC_POLY_CONFIG")
        or DEFAULT_CONFIG_PATH
    )
    with path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Config at {path} must be a mapping")
    environ = env if env is not None else os.environ
    data = apply_env_overlay(data, environ)
    return _settings_from_dict(data, environ)
