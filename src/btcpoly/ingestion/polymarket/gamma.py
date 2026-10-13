"""Polymarket Gamma market resolution for BTC Up/Down windows."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from btcpoly.config import Settings
from btcpoly.db.models import PolymarketMarket
from btcpoly.db.session import session_scope
from btcpoly.ingestion.collectors.http import fetch_text
from btcpoly.ingestion.polymarket.slug import candidate_slugs, market_slug, window_seconds
from btcpoly.ingestion.polymarket.trading_hours import event_bounds, evaluate_trading_gate
from btcpoly.timeutil import utcnow

_TIMEOUT = 12


@dataclass(frozen=True)
class ResolvedMarket:
    market_id: str
    slug: str
    question: str | None
    up_token_id: str
    down_token_id: str
    start_ts: datetime | None
    end_ts: datetime | None
    outcome_prices: tuple[float | None, float | None]
    raw: dict[str, Any]
    accepting_orders: bool = True
    closed: bool = False
    order_min_size: float = 5.0
    tradable: bool = True
    tradable_reason: str = "ok"


def _parse_json_field(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _as_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _pick_up_down_tokens(raw: dict[str, Any]) -> tuple[str, str]:
    tokens = _parse_json_field(raw.get("clobTokenIds")) or []
    outcomes = _parse_json_field(raw.get("outcomes")) or []
    if not isinstance(tokens, list) or len(tokens) < 2:
        raise ValueError("market missing clobTokenIds")
    up_idx, down_idx = 0, 1
    if isinstance(outcomes, list) and len(outcomes) >= 2:
        labels = [str(x).strip().lower() for x in outcomes]
        if "up" in labels:
            up_idx = labels.index("up")
        if "down" in labels:
            down_idx = labels.index("down")
        if up_idx == down_idx:
            up_idx, down_idx = 0, 1
    return str(tokens[up_idx]), str(tokens[down_idx])


def _outcome_prices(raw: dict[str, Any], up_token: str, down_token: str) -> tuple[float | None, float | None]:
    prices = _parse_json_field(raw.get("outcomePrices"))
    tokens = _parse_json_field(raw.get("clobTokenIds")) or []
    if isinstance(prices, list) and isinstance(tokens, list) and len(prices) == len(tokens):
        mapping = {str(tok): _as_float(price) for tok, price in zip(tokens, prices)}
        return mapping.get(up_token), mapping.get(down_token)
    if isinstance(prices, list) and len(prices) >= 2:
        return _as_float(prices[0]), _as_float(prices[1])
    return None, None


def _fetch_market_by_slug(settings: Settings, slug: str) -> dict[str, Any] | None:
    base = settings.polymarket.gamma_base.rstrip("/")
    # Prefer path form; fall back to query list.
    for url in (
        f"{base}/markets/slug/{slug}",
        f"{base}/markets?slug={slug}",
    ):
        try:
            text = fetch_text(url, timeout=_TIMEOUT, attempts=1)
        except RuntimeError:
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and (payload.get("id") or payload.get("conditionId") or payload.get("clobTokenIds")):
            return payload
        if isinstance(payload, list) and payload:
            first = payload[0]
            if isinstance(first, dict):
                return first
    return None


def fetch_market_by_slug(settings: Settings, slug: str) -> dict[str, Any] | None:
    """Public Gamma lookup by market slug."""
    return _fetch_market_by_slug(settings, slug)


def window_bounds_for_slug(slug: str, duration_minutes: int) -> tuple[datetime | None, datetime | None]:
    return _window_bounds(slug, duration_minutes)


def _window_bounds(slug: str, duration_minutes: int) -> tuple[datetime | None, datetime | None]:
    try:
        start_unix = int(slug.rsplit("-", 1)[-1])
    except ValueError:
        return None, None
    start = datetime.fromtimestamp(start_unix, tz=timezone.utc)
    end = datetime.fromtimestamp(start_unix + window_seconds(duration_minutes), tz=timezone.utc)
    return start, end


def resolve_active_market(settings: Settings) -> ResolvedMarket:
    """Resolve the *current* live Up/Down window (same slug Polymarket UI uses)."""
    duration = settings.polymarket.market_duration_minutes
    prefix = settings.polymarket.slug_prefix
    now = utcnow()
    current = market_slug(prefix, duration_minutes=duration, now=now)
    last_error: Exception | None = None

    # Current window first; neighbors only if Gamma has not published current yet.
    for slug in [current, *[s for s in candidate_slugs(prefix, duration_minutes=duration, now=now) if s != current]]:
        try:
            raw = _fetch_market_by_slug(settings, slug)
            if raw is None:
                continue
            resolved_slug = str(raw.get("slug") or slug)
            # Never bind the bot to a past/future neighbor when current exists.
            if slug != current and resolved_slug != current:
                if _fetch_market_by_slug(settings, current) is not None:
                    continue
            up_token, down_token = _pick_up_down_tokens(raw)
            market_id = str(raw.get("conditionId") or raw.get("id") or slug)
            start_ts, end_ts = event_bounds(raw, slug=resolved_slug, duration_minutes=duration)
            if start_ts is None or end_ts is None:
                start_ts, end_ts = _window_bounds(resolved_slug, duration)
            p_up, p_down = _outcome_prices(raw, up_token, down_token)
            gate = evaluate_trading_gate(
                raw,
                slug=resolved_slug,
                duration_minutes=duration,
                slug_prefix=prefix,
                now=now,
            )
            resolved = ResolvedMarket(
                market_id=market_id,
                slug=resolved_slug,
                question=str(raw.get("question") or "") or None,
                up_token_id=up_token,
                down_token_id=down_token,
                start_ts=start_ts,
                end_ts=end_ts,
                outcome_prices=(p_up, p_down),
                raw=raw,
                accepting_orders=gate.accepting_orders,
                closed=gate.closed,
                order_min_size=gate.order_min_size,
                tradable=gate.ok,
                tradable_reason=gate.reason,
            )
            _upsert_market(resolved)
            return resolved
        except Exception as exc:  # noqa: BLE001 — try next slug
            last_error = exc
            continue
    raise RuntimeError(f"no active Polymarket market for {settings.polymarket.slug_prefix}: {last_error}")


def _upsert_market(resolved: ResolvedMarket) -> None:
    now = utcnow()
    with session_scope() as session:
        existing = session.scalar(
            select(PolymarketMarket).where(PolymarketMarket.market_id == resolved.market_id)
        )
        if existing is None:
            session.add(
                PolymarketMarket(
                    market_id=resolved.market_id,
                    slug=resolved.slug,
                    question=resolved.question,
                    up_token_id=resolved.up_token_id,
                    down_token_id=resolved.down_token_id,
                    start_ts=resolved.start_ts,
                    end_ts=resolved.end_ts,
                    ingested_at=now,
                    status="active",
                    raw_json=resolved.raw,
                )
            )
            return
        existing.slug = resolved.slug
        existing.question = resolved.question
        existing.up_token_id = resolved.up_token_id
        existing.down_token_id = resolved.down_token_id
        existing.start_ts = resolved.start_ts
        existing.end_ts = resolved.end_ts
        existing.ingested_at = now
        existing.status = "active"
        existing.raw_json = resolved.raw
