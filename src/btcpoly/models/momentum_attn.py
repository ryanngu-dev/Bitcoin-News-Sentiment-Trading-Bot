"""Momentum + attention volume + post consensus + live Kalshi odds."""

from __future__ import annotations

from btcpoly.models.baseline import (
    MODEL_NAME as MOMENTUM_V0,
    MomentumScore,
    _clip,
    _DEFAULT_K,
    _MAX_SHIFT,
)

MODEL_NAME = "momentum_attn_v1"
_DEFAULT_A = 0.05  # probability shift per unit attn_z_900
_DEFAULT_S = 0.08  # probability shift per unit sentiment_net in [-1, 1]
_DEFAULT_AI = 0.10  # probability shift per unit ai_sentiment_net in [-1, 1]
_MAX_ATTN_SHIFT = 0.18
_MAX_SENT_SHIFT = 0.12
_MAX_AI_SHIFT = 0.15
_AGREE_MAX = 0.06  # extra tilt when BTC move agrees with live book lean


def score_momentum_attn(
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
    attn_z: float = 0.0,
    sentiment_net: float = 0.0,
    ai_sentiment: float = 0.0,
    ai_scored: int = 0,
    ai_credibility: float = 1.0,
    emergency_stop: bool = False,
    k: float = _DEFAULT_K,
    a: float = _DEFAULT_A,
    s: float = _DEFAULT_S,
    ai: float = _DEFAULT_AI,
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

    mom_shift = _clip(k * ret, -_MAX_SHIFT, _MAX_SHIFT)
    attn_shift = _clip(a * float(attn_z), -_MAX_ATTN_SHIFT, _MAX_ATTN_SHIFT)
    sent_shift = _clip(s * float(sentiment_net), -_MAX_SENT_SHIFT, _MAX_SENT_SHIFT)
    ai_shift = 0.0
    if int(ai_scored) > 0:
        cred = max(0.15, min(1.0, float(ai_credibility)))
        ai_shift = _clip(ai * float(ai_sentiment) * cred, -_MAX_AI_SHIFT, _MAX_AI_SHIFT)
    # Live book lean: if short BTC move agrees with Kalshi P(Up), nudge that way.
    market_lean = float(p_up_market) - 0.5
    agree = 0.0
    if mom_shift != 0.0 and market_lean * mom_shift > 0:
        agree = _clip(
            (1.0 if mom_shift > 0 else -1.0) * _AGREE_MAX * min(1.0, abs(market_lean) / 0.25),
            -_AGREE_MAX,
            _AGREE_MAX,
        )

    p_up = _clip(0.5 + mom_shift + attn_shift + sent_shift + ai_shift + agree, 0.05, 0.95)
    p_down = 1.0 - p_up
    edge = p_up - float(p_up_market)
    confidence = min(
        1.0,
        abs(p_up - 0.5) * 2.0
        + min(0.45, abs(edge) * 2.5)
        + min(0.35, abs(float(attn_z)) * 0.08)
        + min(0.25, abs(float(sentiment_net)) * 0.25)
        + min(0.25, abs(float(ai_sentiment)) * 0.25 if int(ai_scored) > 0 else 0.0),
    )

    if spread is not None and spread > max_spread:
        return MomentumScore(
            model_name=MODEL_NAME,
            p_up=p_up,
            p_down=p_down,
            p_up_market=p_up_market,
            edge=edge,
            side="NONE",
            decision="NO_TRADE",
            reason="spread_too_wide",
            entry_price=0.0,
            size=0.0,
            confidence=confidence,
            ret=ret,
            spread=spread,
        )

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

    signal = abs(mom_shift) + abs(attn_shift) + abs(sent_shift) + abs(ai_shift)
    if abs(float(p_up_market) - 0.5) >= 0.40 and signal < 0.03:
        return MomentumScore(
            model_name=MODEL_NAME,
            p_up=p_up,
            p_down=p_down,
            p_up_market=p_up_market,
            edge=edge,
            side="NONE",
            decision="NO_TRADE",
            reason="market_near_resolved",
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


__all__ = ["MODEL_NAME", "MOMENTUM_V0", "score_momentum_attn"]
