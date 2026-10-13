"""Lexicon BTC bullish/bearish consensus from post text (MVP, local, free)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable

# English crypto slang + headlines (posts are often translated to EN already).
_BULLISH = frozenset(
    {
        "bull",
        "bullish",
        "pump",
        "pumps",
        "pumping",
        "moon",
        "mooning",
        "rally",
        "rallies",
        "surge",
        "surges",
        "soar",
        "soars",
        "breakout",
        "ath",
        "all-time",
        "alltime",
        "buy",
        "buying",
        "accumulate",
        "accumulation",
        "inflow",
        "inflows",
        "etf",
        "approval",
        "approved",
        "optimistic",
        "uptrend",
        "green",
        "gains",
        "gain",
        "recovery",
        "rebound",
        "record",
        "highs",
        "breakthrough",
    }
)
_BEARISH = frozenset(
    {
        "bear",
        "bearish",
        "dump",
        "dumps",
        "dumping",
        "crash",
        "crashes",
        "crashs",
        "sell",
        "selling",
        "sold",
        "outflow",
        "outflows",
        "liquidation",
        "liquidations",
        "rekt",
        "fear",
        "panic",
        "collapse",
        "plunge",
        "plunges",
        "drop",
        "drops",
        "downtrend",
        "red",
        "loss",
        "losses",
        "reject",
        "rejection",
        "hack",
        "hacked",
        "ban",
        "banned",
        "lawsuit",
        "sec",
        "crackdown",
        "weak",
        "bleed",
        "bleeding",
    }
)

_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9\-']*")


@dataclass(frozen=True)
class SentimentConsensus:
    scored: int
    bullish: int
    bearish: int
    neutral: int
    net: float  # (bullish - bearish) / scored in [-1, 1]
    bullish_pct: float
    bearish_pct: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "scored": self.scored,
            "bullish": self.bullish,
            "bearish": self.bearish,
            "neutral": self.neutral,
            "net": self.net,
            "bullish_pct": self.bullish_pct,
            "bearish_pct": self.bearish_pct,
        }


def score_text(text: str | None) -> int:
    """Return +1 bullish, -1 bearish, 0 neutral for one post."""
    if not text:
        return 0
    tokens = set(_TOKEN_RE.findall(text.lower()))
    bull = len(tokens & _BULLISH)
    bear = len(tokens & _BEARISH)
    if bull > bear:
        return 1
    if bear > bull:
        return -1
    return 0


def post_blob(text: str | None, raw_json: dict[str, Any] | None = None) -> str:
    parts: list[str] = []
    if text:
        parts.append(str(text))
    payload = raw_json if isinstance(raw_json, dict) else {}
    for key in ("title", "text_en", "body", "summary", "description", "selftext", "content"):
        val = payload.get(key)
        if val:
            parts.append(str(val))
    return " ".join(parts)


def consensus_from_texts(texts: Iterable[str]) -> SentimentConsensus:
    return consensus_from_weighted((t, 1.0) for t in texts)


def consensus_from_weighted(items: Iterable[tuple[str, float]]) -> SentimentConsensus:
    """Weighted bullish/bearish consensus. Weights scale each post's vote."""
    weighted_scores: list[tuple[int, float]] = []
    for text, weight in items:
        w = max(0.0, float(weight))
        if w <= 0:
            continue
        weighted_scores.append((score_text(text), w))
    if not weighted_scores:
        return SentimentConsensus(0, 0, 0, 0, 0.0, 0.0, 0.0)
    scored = len(weighted_scores)
    bullish = sum(1 for s, _ in weighted_scores if s > 0)
    bearish = sum(1 for s, _ in weighted_scores if s < 0)
    neutral = scored - bullish - bearish
    mass = sum(w for _, w in weighted_scores)
    if mass <= 0:
        net = 0.0
    else:
        net = sum(float(s) * w for s, w in weighted_scores) / mass
    bull_mass = sum(w for s, w in weighted_scores if s > 0)
    bear_mass = sum(w for s, w in weighted_scores if s < 0)
    return SentimentConsensus(
        scored=scored,
        bullish=bullish,
        bearish=bearish,
        neutral=neutral,
        net=net,
        bullish_pct=(bull_mass / mass) if mass else 0.0,
        bearish_pct=(bear_mass / mass) if mass else 0.0,
    )
