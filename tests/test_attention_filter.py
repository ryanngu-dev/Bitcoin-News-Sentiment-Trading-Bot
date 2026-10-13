from __future__ import annotations

from datetime import timedelta

from btcpoly.filter.attention import keep_attention_post, localize_post, mentions_btc
from btcpoly.ingestion.schema import RawPost
from btcpoly.monitoring.feed import headline_from_post
from btcpoly.timeutil import utcnow


def test_mentions_btc_ignores_json_key(settings) -> None:
    post = RawPost(
        platform="v2ex",
        post_id="1",
        event_ts=utcnow(),
        text="本周活动 [8.25 日 ~ 8.31 日]",
        raw_json={"title": "本周活动 [8.25 日 ~ 8.31 日]", "member": {"btc": ""}},
    )
    assert mentions_btc(post.text, settings, raw_json=post.raw_json) is False
    assert keep_attention_post(post, settings) is False


def test_mentions_chinese_bitcoin_alias(settings) -> None:
    post = RawPost(
        platform="v2ex",
        post_id="2",
        event_ts=utcnow(),
        text="比特币突破新高",
        raw_json={"title": "比特币突破新高"},
    )
    assert keep_attention_post(post, settings) is True


def test_rejects_stale_posts(settings) -> None:
    stale = RawPost(
        platform="twitter",
        post_id="old",
        event_ts=utcnow() - timedelta(hours=14),
        text="BTC jumps",
        raw_json={"title": "BTC jumps"},
    )
    fresh = RawPost(
        platform="twitter",
        post_id="new",
        event_ts=utcnow() - timedelta(minutes=10),
        text="BTC jumps",
        raw_json={"title": "BTC jumps"},
    )
    assert keep_attention_post(stale, settings) is False
    assert keep_attention_post(fresh, settings) is True


def test_rejects_missing_timestamp(settings) -> None:
    from btcpoly.filter.attention import is_fresh

    assert is_fresh(None, settings, platform="rss") is False


def test_mentions_requires_word_boundary(settings) -> None:
    assert mentions_btc("Franklin Templeton Brings Tokenized BENJI Into ETFs", settings) is False
    assert mentions_btc("Bitcoin traders place a $2.9 million bet", settings) is True
    assert mentions_btc("BTC jumps above 82k", settings) is True


def test_localize_post_translates_title(settings, monkeypatch) -> None:
    monkeypatch.setattr(
        "btcpoly.filter.attention.translate_to_english",
        lambda text, **_k: "Bitcoin hits a new high" if "比特币" in (text or "") else (text or ""),
    )
    post = RawPost(
        platform="v2ex",
        post_id="3",
        event_ts=utcnow(),
        text="比特币突破新高",
        raw_json={"title": "比特币突破新高"},
    )
    out = localize_post(post)
    assert out.raw_json["title"] == "Bitcoin hits a new high"
    assert out.raw_json["title_original"] == "比特币突破新高"
    assert out.text == "Bitcoin hits a new high"


def test_headline_translates_cjk(monkeypatch) -> None:
    monkeypatch.setattr(
        "btcpoly.monitoring.feed.translate_to_english",
        lambda text, **_k: "Weekly Bitcoin meetup",
    )
    headline = headline_from_post(
        "v2ex",
        "ignored",
        author="kikione",
        raw_json={"title": "比特币线下聚会"},
    )
    assert headline.title == "Weekly Bitcoin meetup"
