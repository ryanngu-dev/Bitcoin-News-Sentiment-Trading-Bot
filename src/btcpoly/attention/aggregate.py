"""Attention aggregates and feature snapshots from raw_posts."""

from __future__ import annotations

from datetime import datetime, timedelta
from math import sqrt
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from btcpoly.attention.credibility import source_weight
from btcpoly.attention.ai_score import ai_consensus_for_posts, score_recent_posts_ai
from btcpoly.attention.sentiment import consensus_from_weighted, post_blob
from btcpoly.config import Settings
from btcpoly.db.models import AttentionAggregate, FeatureRow, RawPostRow
from btcpoly.timeutil import to_utc

_FEATURE_WINDOWS = (300, 900)
_Z_HISTORY = 50


def _zscore(value: float, history: list[float]) -> float:
    if len(history) < 2:
        return 0.0
    mean = sum(history) / len(history)
    var = sum((x - mean) ** 2 for x in history) / len(history)
    std = sqrt(var)
    if std < 1e-9:
        # Constant history: treat unit count scale as std so spikes still register.
        std = 1.0
    return (value - mean) / std


def _window_posts(
    session: Session,
    *,
    window_end: datetime,
    window_seconds: int,
) -> list[RawPostRow]:
    end = to_utc(window_end)
    start = end - timedelta(seconds=int(window_seconds))
    return list(
        session.scalars(
            select(RawPostRow).where(
                RawPostRow.event_ts >= start,
                RawPostRow.event_ts <= end,
                RawPostRow.ingested_at <= end,
            )
        ).all()
    )


def build_attention_features(
    session: Session,
    *,
    as_of: datetime,
    market_id: str | None = None,
    windows: tuple[int, ...] = _FEATURE_WINDOWS,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Persist AttentionAggregate + FeatureRow; return slim feature dict for the model."""
    now = to_utc(as_of)
    ai_meta: dict[str, Any] = {"enabled": False, "scored": 0}
    if settings is not None:
        try:
            ai_meta = score_recent_posts_ai(session, settings, as_of=now)
        except Exception as exc:  # noqa: BLE001 — lexicon path must still run
            ai_meta = {"enabled": True, "scored": 0, "error": str(exc)[:200]}

    features: dict[str, Any] = {"as_of": now.isoformat(), "windows": {}, "ai": ai_meta}

    for window_seconds in windows:
        rows = _window_posts(session, window_end=now, window_seconds=window_seconds)
        mention_count = len(rows)
        authors = {str(r.author).strip().lower() for r in rows if r.author}
        unique_authors = len(authors)
        velocity = mention_count / float(window_seconds) if window_seconds else 0.0

        weighted_items: list[tuple[str, float]] = []
        weight_mass = 0.0
        for r in rows:
            raw = r.raw_json if isinstance(r.raw_json, dict) else {}
            w = raw.get("source_weight")
            if w is None:
                feed = raw.get("feed_url")
                w = source_weight(feed_url=str(feed) if feed else None, article_url=r.url)
                # KOL / influence posts get a mild bump when no explicit weight.
                if raw.get("author_influence"):
                    w = max(float(w), 1.20)
            w = float(w)
            weight_mass += w
            weighted_items.append((post_blob(r.text, raw), w))

        consensus = consensus_from_weighted(weighted_items)
        # Attention shock uses credibility-weighted mass (falls back to raw count).
        attention_value = weight_mass if rows else 0.0
        ai_net, ai_scored, ai_cred = ai_consensus_for_posts(session, [int(r.id) for r in rows])

        hist_rows = list(
            session.scalars(
                select(AttentionAggregate)
                .where(AttentionAggregate.window_seconds == int(window_seconds))
                .order_by(AttentionAggregate.window_end.desc())
                .limit(_Z_HISTORY)
            ).all()
        )
        hist_counts = []
        for h in hist_rows:
            feats = h.features if isinstance(h.features, dict) else {}
            if feats.get("weight_mass") is not None:
                hist_counts.append(float(feats["weight_mass"]))
            else:
                hist_counts.append(float(h.mention_count))
        zscore = _zscore(float(attention_value), hist_counts)

        agg = AttentionAggregate(
            window_end=now,
            ingested_at=now,
            window_seconds=int(window_seconds),
            mention_count=mention_count,
            unique_authors=unique_authors,
            velocity=velocity,
            acceleration=None,
            zscore=zscore,
            attention_ratio=None,
            features={
                "mention_count": mention_count,
                "unique_authors": unique_authors,
                "zscore": zscore,
                "weight_mass": weight_mass,
                "sentiment": consensus.to_dict(),
                "ai_sentiment_net": ai_net,
                "ai_sentiment_scored": ai_scored,
                "ai_credibility_mean": ai_cred,
            },
        )
        session.add(agg)

        key = f"w{window_seconds}"
        features["windows"][key] = {
            "window_seconds": window_seconds,
            "mention_count": mention_count,
            "unique_authors": unique_authors,
            "velocity": velocity,
            "zscore": zscore,
            "weight_mass": weight_mass,
            "sentiment": consensus.to_dict(),
            "ai_sentiment_net": ai_net,
            "ai_sentiment_scored": ai_scored,
            "ai_credibility_mean": ai_cred,
        }
        features[f"mention_count_{window_seconds}"] = mention_count
        features[f"unique_authors_{window_seconds}"] = unique_authors
        features[f"attn_z_{window_seconds}"] = zscore
        features[f"weight_mass_{window_seconds}"] = weight_mass
        features[f"sentiment_net_{window_seconds}"] = consensus.net
        features[f"sentiment_bullish_pct_{window_seconds}"] = consensus.bullish_pct
        features[f"sentiment_bearish_pct_{window_seconds}"] = consensus.bearish_pct
        features[f"sentiment_scored_{window_seconds}"] = consensus.scored
        features[f"ai_sentiment_net_{window_seconds}"] = ai_net
        features[f"ai_sentiment_scored_{window_seconds}"] = ai_scored
        features[f"ai_credibility_mean_{window_seconds}"] = ai_cred

    session.add(
        FeatureRow(
            as_of_ts=now,
            ingested_at=now,
            market_id=market_id,
            model_group="C",
            feature_json=features,
        )
    )
    session.flush()
    return features
