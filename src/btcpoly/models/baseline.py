"""Baseline momentum heuristic for paper BTC Up/Down decisions."""

from __future__ import annotations

from dataclasses import dataclass


MODEL_NAME = "momentum_v0"
# Map a 1% BTC move over the short window to ~0.25 probability shift before clip.
_DEFAULT_K = 25.0
_MAX_SHIFT = 0.20


@dataclass(frozen=True)
class MomentumScore:
    model_name: str
    p_up: float
    p_down: float
    p_up_market: float
    edge: float
    side: str
    decision: str
    reason: str
    entry_price: float
    size: float
    confidence: float
    ret: float
    spread: float | None


def _clip(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def score_momentum(
    *,
    ret: float,
    p_up_market: float,
    up_ask: float,
    down_ask: float,
    spread: float | None,
    min_edge: float,
    max_spread: float,
    max_position_usd: float,
    min_confidence: float = 0.0,
    emergency_stop: bool = False,
    k: float = _DEFAULT_K,
) -> MomentumScore:
    if emergency_stop:
        return MomentumScore(
            model_name=MODEL_NAME,
            p_up=0.5,
            p_down=0.5,
            p_up_market=p_up_market,
            edge=0.0,
            side="NONE",
            decision="NO_TRADE",
            reason="emergency_stop",
            entry_price=0.0,
            size=0.0,
            confidence=0.0,
            ret=ret,
            spread=spread,
        )

    if spread is not None and spread > max_spread:
        p_up = _clip(0.5 + _clip(k * ret, -_MAX_SHIFT, _MAX_SHIFT), 0.05, 0.95)
        return MomentumScore(
            model_name=MODEL_NAME,
            p_up=p_up,
            p_down=1.0 - p_up,
            p_up_market=p_up_market,
            edge=p_up - p_up_market,
            side="NONE",
            decision="NO_TRADE",
            reason="spread_too_wide",
            entry_price=0.0,
            size=0.0,
            confidence=abs(p_up - 0.5) * 2.0,
            ret=ret,
            spread=spread,
        )

    shift = _clip(k * ret, -_MAX_SHIFT, _MAX_SHIFT)
    p_up = _clip(0.5 + shift, 0.05, 0.95)
    p_down = 1.0 - p_up
    edge = p_up - p_up_market
    confidence = abs(p_up - 0.5) * 2.0

    if confidence < float(min_confidence):
        return MomentumScore(
            model_name=MODEL_NAME,
            p_up=p_up,
            p_down=p_down,
            p_up_market=p_up_market,
            edge=edge,
            side="NONE",
            decision="NO_TRADE",
            reason="confidence_below_min",
            entry_price=0.0,
            size=0.0,
            confidence=confidence,
            ret=ret,
            spread=spread,
        )

    if abs(edge) < min_edge:
        return MomentumScore(
            model_name=MODEL_NAME,
            p_up=p_up,
            p_down=p_down,
            p_up_market=p_up_market,
            edge=edge,
            side="NONE",
            decision="NO_TRADE",
            reason="edge_below_min",
            entry_price=0.0,
            size=0.0,
            confidence=confidence,
            ret=ret,
            spread=spread,
        )

    if edge > 0:
        entry = float(up_ask)
        side = "UP"
        decision = "BUY_UP"
        reason = "model_above_market"
    else:
        entry = float(down_ask)
        side = "DOWN"
        decision = "BUY_DOWN"
        reason = "model_below_market"

    if entry <= 0.01 or entry >= 0.99:
        return MomentumScore(
            model_name=MODEL_NAME,
            p_up=p_up,
            p_down=p_down,
            p_up_market=p_up_market,
            edge=edge,
            side="NONE",
            decision="NO_TRADE",
            reason="entry_price_extreme",
            entry_price=0.0,
            size=0.0,
            confidence=confidence,
            ret=ret,
            spread=spread,
        )

    size = max(0.0, float(max_position_usd) / entry)
    return MomentumScore(
        model_name=MODEL_NAME,
        p_up=p_up,
        p_down=p_down,
        p_up_market=p_up_market,
        edge=edge,
        side=side,
        decision=decision,
        reason=reason,
        entry_price=entry,
        size=size,
        confidence=confidence,
        ret=ret,
        spread=spread,
    )
