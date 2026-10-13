"""Tests for hybrid LLM sentiment scoring."""

from __future__ import annotations

import json

from sqlalchemy import select

from btcpoly.attention.ai_score import (
    METHOD,
    _parse_scores,
    persist_ai_scores,
    score_posts_with_llm,
    score_recent_posts_ai,
)
from btcpoly.attention.aggregate import build_attention_features
from btcpoly.config import load_settings
from btcpoly.db.models import RawPostRow, SentimentRow
from btcpoly.db.session import init_db, reset_engine, session_scope
from btcpoly.models.momentum_attn import score_momentum_attn
from btcpoly.timeutil import utcnow


def test_parse_scores_from_json_fence() -> None:
    raw = """```json
{"scores":[{"id":"12","score":0.7,"credibility":0.9,"reason":"ETF inflows"}]}
```"""
    parsed = _parse_scores(raw, {"12"})
    assert parsed["12"][0] == 0.7
    assert parsed["12"][1] == 0.9


def test_ai_disabled_without_key(monkeypatch) -> None:
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    reset_engine()
    settings = load_settings(
        env={"BTC_POLY_DATABASE_URL": "sqlite:///:memory:", "BTC_POLY_AI_SENTIMENT": "1"},
        load_dotenv_file=False,
    )
    init_db(settings, url="sqlite:///:memory:")
    with session_scope() as session:
        out = score_recent_posts_ai(session, settings)
    assert out["enabled"] is False


def test_score_posts_with_mock_http(monkeypatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    reset_engine()
    settings = load_settings(
        env={"BTC_POLY_DATABASE_URL": "sqlite:///:memory:", "GROQ_API_KEY": "test-key"},
        load_dotenv_file=False,
    )
    init_db(settings, url="sqlite:///:memory:")
    now = utcnow()
    with session_scope() as session:
        row = RawPostRow(
            platform="rss",
            post_id="ai-1",
            author="coindesk",
            event_ts=now,
            ingested_at=now,
            text="Bitcoin ETF inflows surge as institutions buy",
            raw_json={"title": "Bitcoin ETF inflows surge", "source_weight": 1.3},
        )
        session.add(row)
        session.flush()
        post_id = int(row.id)

        def fake_http(url: str, headers: dict, body: bytes, timeout: float) -> str:
            payload = json.loads(body.decode())
            assert "messages" in payload
            return json.dumps(
                {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "scores": [
                                            {
                                                "id": str(post_id),
                                                "score": 0.8,
                                                "credibility": 0.85,
                                                "reason": "ETF inflows",
                                            }
                                        ]
                                    }
                                )
                            }
                        }
                    ]
                }
            )

        scores = score_posts_with_llm([row], settings, http_post=fake_http)
        assert len(scores) == 1
        assert scores[0].score == 0.8
        assert scores[0].credibility == 0.85
        n = persist_ai_scores(session, scores)
        assert n == 1
        saved = session.scalars(
            select(SentimentRow).where(
                SentimentRow.raw_post_id == post_id,
                SentimentRow.method == METHOD,
            )
        ).one()
        assert saved.score == 0.8
        assert row.raw_json.get("ai_score") == 0.8
        assert row.raw_json.get("ai_credibility") == 0.85
        assert float(row.raw_json.get("source_weight") or 0) > 1.0

        feats = build_attention_features(session, as_of=now, settings=settings)
        assert float(feats["ai_sentiment_net_900"]) == 0.8
        assert int(feats["ai_sentiment_scored_900"]) == 1
        assert float(feats["ai_credibility_mean_900"]) == 0.85


def test_momentum_attn_uses_ai_sentiment() -> None:
    base = score_momentum_attn(
        ret=0.0,
        p_up_market=0.50,
        up_ask=0.51,
        down_ask=0.51,
        spread=0.02,
        min_edge=0.01,
        max_spread=0.1,
        max_position_usd=25,
        attn_z=0.0,
        sentiment_net=0.0,
        ai_sentiment=0.0,
        ai_scored=0,
    )
    ai_hi = score_momentum_attn(
        ret=0.0,
        p_up_market=0.50,
        up_ask=0.51,
        down_ask=0.51,
        spread=0.02,
        min_edge=0.01,
        max_spread=0.1,
        max_position_usd=25,
        attn_z=0.0,
        sentiment_net=0.0,
        ai_sentiment=1.0,
        ai_scored=3,
        ai_credibility=1.0,
    )
    ai_lo = score_momentum_attn(
        ret=0.0,
        p_up_market=0.50,
        up_ask=0.51,
        down_ask=0.51,
        spread=0.02,
        min_edge=0.01,
        max_spread=0.1,
        max_position_usd=25,
        attn_z=0.0,
        sentiment_net=0.0,
        ai_sentiment=1.0,
        ai_scored=3,
        ai_credibility=0.2,
    )
    assert ai_hi.p_up > base.p_up
    assert ai_hi.p_up > ai_lo.p_up
