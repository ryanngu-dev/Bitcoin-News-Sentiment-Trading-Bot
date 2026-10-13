"""Attention aggregates and feature snapshots."""

from btcpoly.attention.aggregate import build_attention_features
from btcpoly.attention.credibility import TRUSTED_MIN_WEIGHT, is_trusted_source, source_weight
from btcpoly.attention.sentiment import consensus_from_texts, consensus_from_weighted, score_text

__all__ = [
    "TRUSTED_MIN_WEIGHT",
    "build_attention_features",
    "consensus_from_texts",
    "consensus_from_weighted",
    "is_trusted_source",
    "score_text",
    "source_weight",
]
